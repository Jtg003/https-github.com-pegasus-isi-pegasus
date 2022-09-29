import logging
import time
import json
import yaml
import re
import os
import sys
import io
from pathlib import Path
from typing import Dict, List, Union
from collections import defaultdict

from Pegasus import braindump
from Pegasus.client import condor

console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter("%(message)s"))

class Status:
    def __init__(self):
        self.log = logging.getLogger(__name__)
        self.log.addHandler(console_handler)
        self.string_logs = io.StringIO()
        self.console_handler2 = logging.StreamHandler(self.string_logs)
        self.console_handler2.setFormatter(logging.Formatter("%(message)s"))
        self.log.addHandler(self.console_handler2)
        self.log.propagate = False

        """Keys are defined as follows
            * `unready`: Jobs blocked by dependencies
            * `ready`: Jobs ready for submission
            * `pre`: PRE-Scripts running
            * `queued`: Submitted jobs
            * `post`: POST-Scripts running
            * `succeeded`: Job completed with success
            * `failed`: Jobs completed with failure
            * `percent_done`: Success percentage
            * `state`: Workflow state
            * `dagname`: Name of workflow
        """
        self.K_UNREADY = "unready"
        self.K_READY = "ready"
        self.K_PRE = "pre"
        self.K_QUEUED = "queued"
        self.K_POST = "post"
        self.K_SUCCEEDED = "succeeded"
        self.K_FAILED = "failed"
        self.K_PERCENT_DONE = "percent_done"
        self.K_DAGNAME = "dagname"
        self.K_DAGSTATE = "state"
        self.K_TOTAL = "total"
        self.K_TOTALS = "totals"
        self.K_SUBMIT_DIR = "submit_directory"

        self.DAG_OK = "Running"
        self.DAG_DONE = "Success"
        self.DAG_FAIL = "Failure"

        self.JS_RUN = "Run"
        self.JS_IDLE = "Idle"
        self.JS_HELD = "Held"
        self.JS_REMOVING = "Del"

        self.root_wf_uuid = None
        self.root_wf_name = None
        self.is_hierarchical = False
        self.dag_tree_struct = None
        self.progress_string = None
        self.show_dirs = None
        self.kill_signal = False
        self.rv_condor_q = None
        
        self.uuid_to_name = {}
        self.job_attr_set = set(['Iwd',
                                 'JobStatus',
                                 'EnteredCurrentStatus',
                                 'pegasus_wf_xformation',
                                 'pegasus_wf_name',
                                 'pegasus_wf_dag_job_id',
                                 'pegasus_wf_dax_job_id',
                                 'Cmd',
                                 'ClusterId',
                                 'pegasus_site',
                                 'JobPrio',
                                 'ClusterId',
                                 'UserLog'
                               ])
        
        self.job_status_codes = { 1:self.JS_IDLE,
                                  2:self.JS_RUN,
                                  3:self.JS_REMOVING,
                                  5:self.JS_HELD
                                 }

        self.status_output = {
                    self.K_TOTALS: {
                        self.K_UNREADY: 0,
                        self.K_READY: 0,
                        self.K_PRE: 0,
                        self.K_QUEUED: 0,
                        self.K_POST: 0,
                        self.K_SUCCEEDED: 0,
                        self.K_FAILED: 0,
                        self.K_PERCENT_DONE: 0.0,
                        self.K_TOTAL: 0
                    },
                    "dags": {
                        "root": {}
                    }
                }


    def fetch_status(self, 
                     submit_dir: str, 
                     json : bool=False, 
                     long : bool=False,
                     dirs : bool=False,
                     legend : bool=False,
                     noqueue : bool=False) -> Union[Dict, None]:
        """
        Shows the workflow status or returns a Dict containing status output
        :return: current status information
        :rtype: Union[dict, None]
        """
        
        self.show_dirs = dirs
        self.get_braindump(submit_dir)
        
        if not noqueue:
            self.rv_condor_q = self.get_q_values()
        
        rv_progress = self.get_progress(submit_dir)
        
        if json :
            if self.rv_condor_q :
                d = defaultdict(list)
                for job in self.rv_condor_q:
                    d[job["pegasus_wf_uuid"]].append({k:v for k,v in job.items() if k in self.job_attr_set})
                self.status_output["condor_jobs"] = defaultdict(dict)
                for uuid,job_list in d.items():
                    dag_name = job_list[0]['UserLog'].split('/')[-1].split('.')[0]
                    if dag_name == self.root_wf_name: dag_name = "root"
                    self.status_output["condor_jobs"][uuid]["DAG_NAME"] = dag_name
                    self.status_output["condor_jobs"][uuid]["DAG_CONDOR_JOBS"] = job_list
            return self.status_output
        
        else:
            if self.rv_condor_q :
                self.show_condor_jobs(self.rv_condor_q,long,legend)
            elif not noqueue :
                self.log.info("\n(No matching jobs found in Condor Q)")
            if rv_progress :
                self.show_job_progress(rv_progress,long,legend)
        self.progress_string = self.string_logs.getvalue()

    def get_braindump(self, submit_dir: str):
        try:
            with (Path(submit_dir) / "braindump.yml").open("r") as f:
                bd = braindump.load(f)
                self.root_wf_uuid = bd.root_wf_uuid
                self.root_wf_name = bd.pegasus_wf_name
        except :
            raise FileNotFoundError(
                "Unable to load braindump file, invalid submit directory!"
            )
        return bd
    
    def get_q_values(self):
        """ Internal method to retrieve Condor Q jobs
        """
        try :
            expression = r""'pegasus_root_wf_uuid == "{}"'"".format(self.root_wf_uuid)
            cmd = ['condor_q','-constraint',expression,'-json']
            return condor._q(cmd)
        except :
            return None

    def show_condor_jobs(self, condor_jobs: list, long: bool, legend: bool):
        """Internal method to display the Condor Q jobs and attributes"""
        
        long_val = int(long)
        column_descr = {           
                    'id'      : ['',': Condor cluster ID '],
                    'site'    : ['',': Job site\n'],
                    'stat'    : 'Condor job status',
                    'in_state': 'Time job spent in current Condor status',
                    'job'     : 'Workflow-ID or DAG-Node ID'
                    }
        
        if long:
            idcol='{:^5}'.format('ID')
            st = '{:^7}'.format('SITE')
        else:
            idcol=''
            st=''
        
        if legend: 
                self.log.info("\n{}{}{}{}STAT: {}  IN_STATE: {}  JOB: {}".format(idcol.strip(),column_descr['id'][long_val],
                                                                                 st.rstrip(),column_descr['site'][long_val],
                                                                                 column_descr['stat'],
                                                                                 column_descr['in_state'],
                                                                                 column_descr['job']))
                
        self.log.info("\n{}{}{:5}{:^11}{:25}".format(idcol,st,'STAT','IN_STATE','JOB'))
        
        job_counts = {self.JS_IDLE:0,
                       self.JS_RUN:0,
                       self.JS_HELD:0,
                       self.JS_REMOVING:0
                      }
        
        d = defaultdict(list)
        
        for job in condor_jobs:
            d[job["pegasus_wf_uuid"]].append({k:v for k,v in job.items() if k in self.job_attr_set})
        
        def print_q(wf_uuid, prefix: str = ''):
            space =  '  '
            bar = '\u2503 '
            t =    '\u2523\u2501'
            L =   '\u2517\u2501'
            jobs_list = d[wf_uuid]
            pointers = [t] * (len(jobs_list) - 1) + [L]
            for pointer, job in zip(pointers, jobs_list):
                status = self.job_status_codes[job['JobStatus']]
                if long:
                    jobid = '{:^5}'.format(job["ClusterId"])
                    site = '{:^7}'.format(job["pegasus_site"])
                else:
                    jobid = ''
                    site = ''
                job_counts[status] += 1
                in_state = self.get_time(int(time.time() - job['EnteredCurrentStatus']))
                if job['pegasus_wf_xformation'] == 'pegasus::dagman':
                    job_name = '{} ({})'.format(job['pegasus_wf_name'],job['Iwd'])
                else :
                    job_name = prefix + pointer + job['pegasus_wf_dag_job_id']
                self.log.info("{}{}{:^5}{:^11}{:25}".format(jobid,site,status,in_state,job_name))
                
                if job['pegasus_wf_xformation'] == 'condor::dagman':
                    extension = bar if pointer == t else space
                    print_q(self.get_braindump(Path(job["Iwd"])).wf_uuid, prefix=prefix+extension)
                    
        print_q(self.root_wf_uuid)
        
        idle = {False:'', True:'I:{} '.format(job_counts["Idle"])}
        run = {False:'', True:'R:{} '.format(job_counts["Run"])}
        held = {False:'' , True:'H:{} '.format(job_counts["Held"])}
        rem = {False:'' , True:'X:{}'.format(job_counts["Del"])}
        total_jobs = len(condor_jobs)
        s = {False:'', True:'s'}
        
        summary_line = "Summary: {} Condor job{} total ({}{}{}{})".format(total_jobs,
                                                                          s[bool(abs(1-total_jobs))],
                                                                          idle[bool(job_counts["Idle"])],
                                                                          run[bool(job_counts["Run"])],
                                                                          held[bool(job_counts["Held"])],
                                                                          rem[bool(job_counts["Del"])])
        self.log.info(summary_line[:-1].rstrip(' ')+')')        

    def get_time(self, time) -> str:
        """Internal method to get time elapsed for a job in dd:hh:mm:ss format"""
        day = "{0:0=2d}".format(time // (24 * 3600))
        time = time % (24 * 3600)
        hour = "{0:0=2d}".format(time // 3600)
        time %= 3600
        minutes = "{0:0=2d}".format(time // 60)
        time %= 60
        seconds = "{0:0=2d}".format(time)
        val=''
        for each in (day, hour):
            if int(each) : val+= (each+':')
        return '{}{}:{}'.format(val,minutes,seconds)
    
    
    def get_progress(self, submit_dir: str) -> Dict:
        """Internal method to get workflow progress by parsing dagman.out file"""
        
        dagman_list = self.get_all_dagmans(Path(submit_dir))
        #if wrong submit_dir is given or no dagman files found
        if not dagman_list:
            return None
        
        dag_dict = None
        for dagman_file in dagman_list:            
            wf_name = dagman_file.split('/')[-1].split('.')[0]
            
            #if the directory is root directory
            if dagman_file[:dagman_file.rfind('/')] == submit_dir:
                dag_dict = "root"
                dag_name = '{}.dag'.format(wf_name)
            #if the directory is a sub-workflow directory
            else:
                dag_dict = wf_name
                submit = os.path.relpath(os.path.dirname(dagman_file),submit_dir)
                if self.show_dirs : 
                    dag_name = '{}/{}.dag'.format(submit,wf_name)
                else:
                    dag_name = '{}.dag'.format(wf_name)
            #initializing a dict for each DAG, to be added to the common structure returned
            self.status_output["dags"][dag_dict] = {
                                self.K_UNREADY: 0,
                                self.K_READY: 0,
                                self.K_PRE: 0,
                                self.K_QUEUED: 0,
                                self.K_POST: 0,
                                self.K_SUCCEEDED: 0,
                                self.K_FAILED: 0,
                                self.K_PERCENT_DONE: 0.0,
                                self.K_TOTAL: 0,
                                self.K_DAGNAME: dag_name,
                                self.K_DAGSTATE: None
                            }
            self.parse_dagman_file(dagman_file, dag_name, dag_dict)
        
        #updating the TOTALS dict after 
        for key in list(self.status_output[self.K_TOTALS].keys()):
            key_total_val = 0
            if key != "percent_done":
                for each_dag in self.status_output["dags"]:
                    key_total_val += self.status_output["dags"][each_dag][key]
                self.status_output[self.K_TOTALS][key] = key_total_val
        
        #%Done for the entire workflow
        if self.status_output[self.K_TOTALS][self.K_TOTAL]:
            total_percent_done = float("{:.2f}".format((self.status_output[self.K_TOTALS][self.K_SUCCEEDED]/
                                                       self.status_output[self.K_TOTALS][self.K_TOTAL])*100))
            self.status_output[self.K_TOTALS]["percent_done"] = total_percent_done
        
        #check if wf contains subworkflows
        if len(dagman_list) > 1:
            self.is_hierarchical = True
            self.dag_tree_struct = list(self.get_dag_tree_structure(dagman_list,submit_dir))
        else:
            self.dag_tree_struct = ["root"]
        
        root_dag_state = self.status_output['dags']['root']['state']
        if root_dag_state == 'Success' or root_dag_state == 'Failure':
            self.kill_signal = True
        
        return self.status_output

    
    def parse_dagman_file(self, dagman_file, dag_name, dag_dict):
        #parsing the dagman.out file
        with open(dagman_file,'r') as f:
            for line in f:
                dag_status_line = re.match(r'\d\d/\d\d/\d\d\ \d\d:\d\d:\d\d DAG status',line)
                #MM/DD/YY HH:MM:SS DAG status: 0 (DAG_STATUS_OK)

                nodes_total_line = re.match(r'(?=.*(nodes total:))',line)
                #MM/DD/YY HH:MM:SS Of 10 nodes total:

                jobs_progress_line = re.match(r'\d\d/\d\d/\d\d\ \d\d:\d\d:\d\d\ (\s*([0-9])){7}',line)
                #    0        1       2       3       4        5      6        7          8    <-- indices
                #MM/DD/YY hh:mm:ss  Done     Pre   Queued    Post   Ready   Un-Ready   Failed
                #MM/DD/YY hh:mm:ss   ===     ===      ===     ===     ===        ===      ===
                #MM/DD/YY hh:mm:ss    12       0       22       0       0         83        0

                if dag_status_line:
                        dag_status = int(line.split()[4])
                if nodes_total_line:
                        total_nodes = line.split()[3]
                if jobs_progress_line:
                        temp_values = line.split()
                        self.status_output["dags"][dag_dict] = {
                                self.K_UNREADY: int(temp_values[7]),
                                self.K_READY: int(temp_values[6]),
                                self.K_PRE: int(temp_values[3]),
                                self.K_QUEUED: int(temp_values[4]),
                                self.K_POST: int(temp_values[5]),
                                self.K_SUCCEEDED: int(temp_values[2]),
                                self.K_FAILED: int(temp_values[8]),
                                self.K_PERCENT_DONE: float("{:.2f}".format((int(temp_values[2])/int(total_nodes))*100)),
                                self.K_TOTAL: int(total_nodes),
                                self.K_DAGNAME: dag_name,
                            }
                        
                        # Non-zero exitcode shows Failure
                        if dag_status:
                            self.status_output["dags"][dag_dict][self.K_DAGSTATE] = self.DAG_FAIL

                        # Else Zero exitcode shows DAG_OK status
                        else:

                            #Check for Success DAG status
                            if self.status_output["dags"][dag_dict][self.K_PERCENT_DONE] == 100.0 :
                                self.status_output["dags"][dag_dict][self.K_DAGSTATE] = self.DAG_DONE

                            #Else it's Running DAG status
                            else:
                                self.status_output["dags"][dag_dict][self.K_DAGSTATE] = self.DAG_OK
                    
                #if dagman.out file has no job progress updates due to DAG failure
                else:
                        exit_status_line = re.match(r'(?=.*(EXITING WITH STATUS \d))',line)
                        if exit_status_line and self.status_output["dags"][dag_dict][self.K_DAGSTATE] == None:
                            exit_status = int(line.split()[-1])
                            if exit_status:
                                self.status_output["dags"][dag_dict][self.K_DAGSTATE] = self.DAG_FAIL    


    def get_all_dagmans(self, submit_dir:str) -> List:
        """
        Internal method which receives a submit directory
        :return List: .dagman.out files with absolute paths
        """
        dagmans = []
        # Traversing the dirs and sub-dirs in DFS manner
        for root, directories, files in os.walk(submit_dir, topdown=True, followlinks=False):
            for file in files:
                if file.endswith('.dag.dagman.out'):
                    dagmans.append(os.path.join(root, file))
                    
        return dagmans

    
    def show_job_progress(self, values: dict, long: bool, legend: bool):
        """Internal method to display workflow progress"""
        
        long_val = int(long)
        
        column_descr = {           
                    'unready'     : 'Jobs blocked by dependencies',
                    'ready'       : 'Jobs ready for submission',
                    'pre'         : 'PRE-Scripts running',
                    'queued'      : 'Submitted jobs',
                    'post'        : 'POST-Scripts running',
                    'completed'   : 'Job completed with success',
                    'failed'      : 'Jobs completed with failure',
                    'percent_done': 'Success percentage',
                    'state'       : ['', ': Workflow state '], #Long=False, Long=true
                    'dagname'     : ['', ': Name of workflow']
                    }
        
        column_names = {            # Long = False          ,     Long = True
                    'unready'     : ['{:^8}'.format('UNREADY'), '{:^7}'.format('UNREADY')],
                    'ready'       : ['{:^8}'.format('READY'), '{:^7}'.format('READY')],
                    'pre'         : ['{:^6}'.format('PRE'), '{:^5}'.format('PRE')],
                    'queued'      : ['{:^8}'.format('QUEUED'), '{:^6}'.format('IN_Q')],
                    'post'        : ['{:^8}'.format('POST'), '{:^6}'.format('POST')],
                    'completed'   : ['{:^9}'.format('SUCCESS'), '{:^6}'.format('DONE')],
                    'failed'      : ['{:^9}'.format('FAILURE'), '{:^6}'.format('FAIL')],
                    'percent_done': ['{:^8}'.format('%DONE'), '{:^6}'.format('%DONE')],
                    'state'       : ['', '{:^8}'.format('STATE')],
                    'dagname'     : ['', '{:25}'.format('DAGNAME')]
                    }
        
        if legend:
            self.log.info("\nUNREADY: {}  READY: {}  PRE : {}\n{}: {}  POST: {}  {}: {}\n{}: {}  %DONE: {} {}{}{}{}".format(
                column_descr['unready'],column_descr['ready'],column_descr['pre'],
                column_names['queued'][long_val].strip(),column_descr['queued'],
                column_descr['post'], column_names['completed'][long_val].strip(),column_descr['completed'],
                column_names['failed'][long_val].strip(),column_descr['failed'],
                column_descr['percent_done'],column_names['state'][long_val].strip(),column_descr['state'][long_val],
                column_names['dagname'][long_val].strip(),column_descr['dagname'][long_val]))
        
        self.log.info("\n{}{}{}{}{}{}{}{}{}{}".format(column_names['unready'][long_val],
                                                       column_names['ready'][long_val],
                                                       column_names['pre'][long_val],
                                                       column_names['queued'][long_val],
                                                       column_names['post'][long_val],
                                                       column_names['completed'][long_val],
                                                       column_names['failed'][long_val],
                                                       column_names['percent_done'][long_val],
                                                       column_names['state'][long_val],
                                                       column_names['dagname'][long_val]))

        if long_val == 0:
            dag_totals = values["totals"]
            self.log.info("{:^8}{:^8}{:^6}{:^8}{:^8}{:^9}{:^9}{:^8}".format(dag_totals["unready"],
                                                                dag_totals["ready"],
                                                                dag_totals["pre"],
                                                                dag_totals["queued"],
                                                                dag_totals["post"],
                                                                dag_totals["succeeded"],
                                                                dag_totals["failed"],
                                                                dag_totals["percent_done"]))
        
        else :
            
            if self.is_hierarchical:
                total_name = 'TOTALS({} jobs)'.format(values["totals"]["total"])
                self.dag_tree_struct.append(("totals",total_name))
            
            for index, each_dag in enumerate(self.dag_tree_struct):
                if not index :
                    dag_dict = values["dags"]["root"]
                    state = dag_dict[self.K_DAGSTATE]
                    name = values["dags"]["root"]['dagname']
                elif each_dag[0] == "totals": 
                    dag_dict = values["totals"]
                    state = ' '
                    name = each_dag[1]
                else:
                    dag = each_dag[0].split('.')[0]
                    dag_dict = values["dags"][dag]
                    state = dag_dict[self.K_DAGSTATE]
                    name = each_dag[1]
                  
                self.log.info("{:^7}{:^7}{:^5}{:^6}{:^6}{:^6}{:^6}{:^6}{:^8}{:25}".format(dag_dict[self.K_UNREADY],
                                                                                           dag_dict[self.K_READY],
                                                                                           dag_dict[self.K_PRE],
                                                                                           dag_dict[self.K_QUEUED],
                                                                                           dag_dict[self.K_POST],
                                                                                           dag_dict[self.K_SUCCEEDED],
                                                                                           dag_dict[self.K_FAILED],
                                                                                           dag_dict[self.K_PERCENT_DONE],
                                                                                           state,
                                                                                           name,
                                                                                          ))
        
        dag_state_counts = {"Running":0,"Success":0,"Failure":0}
        for each_dag in values["dags"]:
            dag_state_counts[values["dags"][each_dag]['state']] += 1
            
        done = {False:'', True:'Success:{} '.format(dag_state_counts["Success"])}
        fail = {False:'', True:'Failure:{} '.format(dag_state_counts["Failure"])}
        run = {False:'' , True:'Running:{}'.format(dag_state_counts["Running"])}
        total_dags = len(values['dags'])
        s = {False:'', True:'s'}
        
        summary_line = "Summary: {} DAG{} total ({}{}{})".format(total_dags,
                                                                 s[bool(abs(1-total_dags))],
                                                                 done[bool(dag_state_counts["Success"])],
                                                                 fail[bool(dag_state_counts["Failure"])],
                                                                 run[bool(dag_state_counts["Running"])])
        self.log.info(summary_line[:-1].rstrip(' ')+')\n')


    def get_dag_tree_structure(self, dagman_list, submit_dir):
        root_dir_name = submit_dir.rstrip('/').split('/')[-1]
        dags = [each_path[each_path.find(root_dir_name):] for each_path in dagman_list]
        root_dag_name = self.status_output["dags"]["root"]["dagname"]
        levels_dict = {1:(root_dag_name+'/')}
        curr_hr = [root_dag_name]
        paths = []
        
        for i in range(1,len(dags)):
            curr_level = dags[i].count('/')
            prev_level = dags[i-1].count('/')
            curr_dag_name = '{}.dag'.format(dags[i].split('/')[-1].split('.')[0])
            if curr_level <= prev_level:
                diff = prev_level - curr_level
                for i in range((diff//3)+1):
                    curr_hr.pop()
            curr_hr.append(('/'+curr_dag_name))
            paths.append(''.join(curr_hr))
        
        def nested_dict():
            return defaultdict(nested_dict)
        def default_to_regular(d):
            if isinstance(d, defaultdict):
                d = {k: default_to_regular(v) for k, v in d.items()}
            return d
        
        new_path_dict = nested_dict()
        for path in paths:
            parts = path.split('/')
            if parts:
                sub_dict = new_path_dict
                for key in parts[:]:
                    sub_dict = sub_dict[key]
        
        return list(self.print_tree(default_to_regular(new_path_dict)))
        
        
    def print_tree(self, paths: dict, prefix: str = ''):
        space =  '  '
        bar = '\u2502 '
        t =    '\u251c\u2500'
        L =   '\u2514\u2500'
        pointers = [t] * (len(paths) - 1) + [L]
        for pointer, path in zip(pointers, paths):
            wf = path.split('.')[0]
            if wf == self.root_wf_name:
                k = "root"
            else:
                k = wf
            name = self.status_output["dags"][k]["dagname"]
            yield (path, prefix + pointer + name)
            if isinstance(paths[path], dict): 
                extension = bar if pointer == t else space
                yield from self.print_tree(paths[path], prefix=prefix+extension) 
