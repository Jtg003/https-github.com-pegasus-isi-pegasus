#include <errno.h>
#include <stdlib.h>
#include <unistd.h>
#include <stdio.h>
#include <sys/wait.h>
#include <sys/time.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <signal.h>
#include <math.h>
#include <mpi.h>
#include <sys/resource.h>
#include <map>
#include <poll.h>
#include <memory>

#include "strlib.h"
#include "worker.h"
#include "protocol.h"
#include "log.h"
#include "failure.h"
#include "tools.h"

using std::string;
using std::map;
using std::vector;
using std::list;

extern char **environ;

static void log_signal(int signo) {
    log_error("Caught signal %d", signo);
}

PipeForward::PipeForward(string varname, string filename, int readfd, int writefd) {
    this->varname = varname;
    this->filename = filename;
    this->readfd = readfd;
    this->writefd = writefd;
}

PipeForward::~PipeForward() {
    // Make sure the pipes are closed before
    // deleting them to prevent descriptor leaks
    // in the case of failures
    this->close();
}

const char *PipeForward::data() {
    return this->buffer.data();
}

size_t PipeForward::size() {
    return this->buffer.size();
}

string PipeForward::destination() {
    return filename;
}

void PipeForward::append(char *buff, int size) {
    this->buffer.append(buff, size);
}

int PipeForward::read() {
    char buff[BUFSIZ];
    int rc = ::read(readfd, buff, BUFSIZ);
    if (rc > 0) {
        // We got some data, save it to the pipe's data buffer
        this->append(buff, rc);
    }
    return rc;
}

void PipeForward::close() {
    this->closeread();
    this->closewrite();
}

void PipeForward::closeread() {
    if (this->readfd != -1) {
        if (::close(this->readfd)) {
            log_error("Error closing read end of pipe %s: %s", 
                    varname.c_str(), strerror(errno));
        }
        this->readfd = -1;
    }
}

void PipeForward::closewrite() {
    if (this->writefd != -1) {
        if (::close(this->writefd)) {
            log_error("Error closing write end of pipe %s: %s", 
                    varname.c_str(), strerror(errno));
        }
        this->writefd = -1;
    }
}

FileForward::FileForward(const string &srcfile, const string &destfile, char *buff, size_t buffsize) {
    this->srcfile = srcfile;
    this->destfile = destfile;
    this->buff = buff;
    this->buffsize = buffsize;
}

FileForward::~FileForward() {
    delete buff;
}

const char *FileForward::data() {
    return this->buff;
}

size_t FileForward::size() {
    return this->buffsize;
}

string FileForward::destination() {
    return destfile;
}

TaskHandler::TaskHandler(Worker *worker, string &name, string &command, string &id, unsigned memory, unsigned cpus, const map<string,string> &pipe_forwards, const map<string,string> &file_forwards) {
    this->worker = worker;
    this->name = name;
    split_args(this->args, command);
    this->id = id;
    this->memory = memory;
    this->cpus = cpus;
    this->pipe_forwards = pipe_forwards;
    this->file_forwards = file_forwards;
    this->start = 0;
    this->finish = 0;
}

TaskHandler::~TaskHandler() {
    // Delete all the forwards
    for (unsigned i=0; i<forwards.size(); i++) {
        delete forwards[i];
    }
}

/** Compute the elapsed runtime of the task */
double TaskHandler::elapsed() {
    if (this->start == 0) {
        return 0.0;
    }
    if (this->finish == 0) {
        return current_time() - this->start;
    }
    return this->finish - this->start;
}

/** 
 * Do all the operations required for the child process after
 * fork() up to and including execve()
 */
void TaskHandler::child_process() {
    
    // Redirect stdout/stderr. We do this first thing so that any
    // of the error messages printed before the execve show up in
    // the task stdout/stderr where they belong. Otherwise, we could
    // end up shipping a lot of error messages to the master process.
    if (dup2(worker->out, STDOUT_FILENO) < 0) {
        log_fatal("Error redirecting stdout of task %s: %s", 
            name.c_str(), strerror(errno));
        exit(1);
    }
    if (dup2(worker->err, STDERR_FILENO) < 0) {
        log_fatal("Error redirecting stderr of task %s: %s", 
            name.c_str(), strerror(errno));
        exit(1);
    }
    
    // Close the read end of all the pipes. This should force a
    // SIGPIPE in the case that the parent process closes the read
    // end of the pipe while we are writing to it.
    for (unsigned i=0; i<pipes.size(); i++) {
        pipes[i]->closeread();
    }
    
    // Create argument structure
    unsigned nargs = args.size();
    char **argp = new char*[nargs+1];
    for (unsigned i=0; i<nargs; i++) {
        string arg = args.front();
        argp[i] = new char[arg.size()+1];
        if (sprintf(argp[i], "%s", arg.c_str()) == -1) {
            log_fatal("Unable to create arguments: %s", strerror(errno));
            exit(1);
        }
        args.pop_front();
    }
    argp[nargs] = NULL;
    
    // Create environment structure. We need to copy the worker's
    // environment, but also add env variables for the pipes used
    // to forward I/O from the task.
    unsigned nenvs = 0;
    while (environ[nenvs]) nenvs++;
    char **envp = new char*[nenvs+pipes.size()+1];
    for (unsigned i=0; i<nenvs; i++) {
        envp[i] = environ[i];
    }
    for (unsigned i=0; i<pipes.size(); i++) {
        PipeForward *p = pipes[i];
        envp[nenvs+i] = new char[p->varname.size()+11];
        if (sprintf(envp[nenvs+i], "%s=%d", p->varname.c_str(), p->writefd) == -1) {
            log_fatal("Unable to create environment: %s", strerror(errno));
            exit(1);
        }
    }
    envp[nenvs+pipes.size()] = NULL;
    
    // If the executable is not an absolute or relative path, then search PATH
    string executable = argp[0];
    if (executable.find("/") == string::npos) {
        executable = pathfind(executable);
    }
    
    // Set strict resource limits
    if (worker->strict_limits && memory > 0) {
        rlim_t bytes = memory * 1024 * 1024;
        struct rlimit memlimit;
        memlimit.rlim_cur = bytes;
        memlimit.rlim_max = bytes;
        
        // These limits don't always seem to work, so set all of them. In fact,
        // they don't seem to work at all on OS X.
        if (setrlimit(RLIMIT_DATA, &memlimit) < 0) {
            log_error("Unable to set memory limit (RLIMIT_DATA) for task %s: %s",
                name.c_str(), strerror(errno));
        }
        if (setrlimit(RLIMIT_STACK, &memlimit) < 0) {
            log_error("Unable to set memory limit (RLIMIT_STACK) for task %s: %s",
                name.c_str(), strerror(errno));
        }
        if (setrlimit(RLIMIT_RSS, &memlimit) < 0) {
            log_error("Unable to set memory limit (RLIMIT_RSS) for task %s: %s",
                name.c_str(), strerror(errno));
        }
        if (setrlimit(RLIMIT_AS, &memlimit) < 0) {
            log_error("Unable to set memory limit (RLIMIT_AS) for task %s: %s",
                name.c_str(), strerror(errno));
        }
    }
    
    // Exec process
    execve(executable.c_str(), argp, envp);
    fprintf(stderr, "Unable to exec command %s for task %s: %s\n", 
        executable.c_str(), name.c_str(), strerror(errno));
    exit(1);
}

/* Send all I/O forwarded data to master */
void TaskHandler::send_io_data() {
    for (unsigned i = 0; i < this->forwards.size(); i++) {
        Forward *f = this->forwards[i];
        log_trace("Task %s: Forward %s got %d bytes", name.c_str(), 
                f->destination().c_str(), f->size());

        // Don't bother to send the message if there is no data
        if (f->size() == 0) {
            continue;
        }
        
        IODataMessage iodata(this->name, f->destination(), f->data(), f->size());
        send_message(&iodata, 0);
    }
}

/* unlink() all I/O forwarded files */
void TaskHandler::delete_files() {
    map<string,string>::iterator i;
    for (i = file_forwards.begin(); i != file_forwards.end(); i++) {
        string srcfile = i->first;
        if (unlink(srcfile.c_str())) {
            log_debug("Task %s: Error unlinking forwarded file %s: %s", 
                    name.c_str(), srcfile.c_str(), strerror(errno));
        }
    }
}

/* Read all I/O forwarded files into memory */
int TaskHandler::read_file_data() {
    map<string,string>::iterator i;
    for (i = file_forwards.begin(); i != file_forwards.end(); i++) {
        string srcfile = i->first;
        string destfile = i->second;
        
        // Make sure the file exists
        struct stat st;
        if (stat(srcfile.c_str(), &st)) {
            if (errno == ENOENT) {
                // If the file does not exist, then we just skip it. We assume that
                // the user wants to have some tasks exit successfully without 
                // producing any output data.
                log_debug("Task %s: file %s does not exist", name.c_str(), 
                        srcfile.c_str());
                continue;
            }
            log_error("Task %s: stat failed on file %s: %s", 
                    name.c_str(), srcfile.c_str(), strerror(errno));
            return -1;
        }
        
        // Make sure it is a regular file
        if (!S_ISREG(st.st_mode)) {
            log_error("Task %s: %s is not a file", name.c_str(), srcfile.c_str());
            return -1;
        }
        
        // Check the size of the file
        size_t size = st.st_size;
        if (size > 1024*1024) {
            log_error("Task %s: File %s is too large", name.c_str(), srcfile.c_str());
            return -1;
        }
        
        // Read the data into a buffer
        char *buff = new char[size];
        if (read_file(srcfile, buff, size) != size) {
            log_error("Task %s: Unable to read %s: %s", name.c_str(), srcfile.c_str(), 
                    strerror(errno));
            delete buff;
            return -1;
        }
        
        FileForward *fwd = new FileForward(srcfile, destfile, buff, size);
        files.push_back(fwd);
        forwards.push_back(fwd);
    }
    
    return 0;
}

/* Send info about the task back to the master */
void TaskHandler::send_result() {
    ResultMessage res(this->name, this->status, this->elapsed());
    send_message(&res, 0);
}

/* Fork the task and wait for it to exit */
int TaskHandler::run_process() {
    
    // Record start time of task
    this->start = current_time();
    
    // Create pipes for all of the pipe forwards
    for (map<string,string>::iterator i = pipe_forwards.begin(); i != pipe_forwards.end(); i++) {
        string varname = i->first;
        string filename = i->second;
        int pipefd[2];
        if (pipe(pipefd) < 0) {
            log_error("Unable to create pipe for task %s: %s",
                    name.c_str(), strerror(errno));
            return -1;
        }
        log_trace("Pipe: %s = %s", varname.c_str(), filename.c_str());
        PipeForward *p = new PipeForward(varname, filename, pipefd[0], pipefd[1]);
        pipes.push_back(p);
        forwards.push_back(p);
    }
    
    // Fork a child process to execute the task
    pid_t pid = fork();
    if (pid < 0) {
        // Fork failed
        log_error("Unable to fork task %s: %s", name.c_str(), strerror(errno));
        return -1;
    }
    
    if (pid == 0) {
        child_process();
    }
    
    // Close the write end of all the pipes
    for (unsigned i=0; i<pipes.size(); i++) {
        pipes[i]->closewrite();
    }
    
    // Create a structure to hold all of the pipes
    // we need to read from
    map<int, PipeForward *> reading;
    for (unsigned i=0; i<pipes.size(); i++) {
        reading[pipes[i]->readfd] = pipes[i];
    }
    
    bool poll_failure = false;
    std::auto_ptr<struct pollfd> fdhandle(new struct pollfd[pipe_forwards.size()]);
    struct pollfd *fds = fdhandle.get();
    
    // TODO Refactor the pipe/polling into another method
    
    // While there are pipes to read from
    while (reading.size() > 0) {
        
        // Set up inputs for poll()
        int nfds = 0;
        for (map<int, PipeForward *>::iterator p=reading.begin(); p!=reading.end(); p++) {
            PipeForward *pipe = (*p).second;
            fds[nfds].fd = pipe->readfd;
            fds[nfds].events = POLLIN;
            nfds++;
        }
        
        log_trace("Polling %d pipes", nfds);
        
        int timeout = -1;
        int rc = poll(fds, nfds, timeout);
        if (rc <= 0) {
            // If this happens then we are in trouble. The only thing we
            // can do is log it and break out of the loop. What should happen
            // then is that we close all the pipes, which will force the child
            // to get SIGPIPE and fail.
            log_error("poll() failed for task %s: %s", name.c_str(), 
                      strerror(errno));
            poll_failure = true;
            goto after_poll_loop;
        }
        
        // One or more of the file descriptors are readable, find out which ones
        for (int i=0; i<nfds; i++) {
            int revents = fds[i].revents;
            int fd = fds[i].fd;
            
            // This descriptor has no events 
            if (revents == 0) {
                continue;
            }
            
            if (revents & POLLIN) {
                rc = reading[fd]->read();
                if (rc < 0) {
                    // If this happens we have a serious problem and need the
                    // task to fail. Cause the failure by breaking out of the
                    // loop and closing the pipes.
                    log_error("Error reading from pipe %d: %s", 
                              fd, strerror(errno));
                    poll_failure = true;
                    goto after_poll_loop;
                } else if (rc == 0) {
                    // Pipe was closed, EOF. Stop polling it.
                    log_trace("Pipe %d closed", fd);
                    reading.erase(fd);
                } else {
                    log_trace("Read %d bytes from pipe %d", rc, fd);
                }
            }
            
            if (revents & POLLHUP) {
                log_trace("Hangup on pipe %d", fd);
                // It is important that we don't stop reading the fd here
                // because in the next poll we may get more data if our
                // buffer wasn't big enough to get everything on this read.
                // However, on Linux, if POLLIN was not set, then the pipe
                // is really closed and we need to clean it up here.
                if (! (revents & POLLIN)) {
                    reading.erase(fd);
                }
            }
            
            if (revents & POLLERR) {
                // I don't know what would cause this. I think possibly it can
                // only happen for hardware devices and not pipes. In case it
                // does happen we will log it here and fail the task.
                log_error("Error on pipe %d", fd);
                poll_failure = true;
                goto after_poll_loop;
            }
        }
    }
    
after_poll_loop: 
    // Close the pipes here just in case something happens above 
    // so that we aren't deadlocked waiting for a process that is itself 
    // deadlocked waiting for us to read data off the pipe. Instead, 
    // if we close the pipes here, then the task will get SIGPIPE and we 
    // can wait on it successfully.
    for (unsigned i=0; i<pipes.size(); i++) {
        pipes[i]->close();
    }
    
    // Wait for task to complete
    int exitcode;
    if (waitpid(pid, &exitcode, 0) < 0) {
        log_error("Failed waiting for task %s: %s", name.c_str(), 
                strerror(errno));
        return -1;
    }
    
    // Record the finish time of the task
    this->finish = current_time();
    
    double runtime = elapsed();
    
    if (WIFEXITED(exitcode)) {
        log_debug("Task %s exited with status %d (%d) in %f seconds", 
            name.c_str(), WEXITSTATUS(exitcode), exitcode, runtime);
    } else {
        log_debug("Task %s exited on signal %d (%d) in %f seconds", 
            name.c_str(), WTERMSIG(exitcode), exitcode, runtime);
    }
    
    // We have to wait till here to return in the case of poll_failure
    // because we need to wait() on the task
    if (poll_failure) {
        return -1;
    }
    
    return exitcode;
}

/* Write cluster-task record to task stdout */
void TaskHandler::write_cluster_task() {
    // If the Pegasus id is missing then don't add it to the message
    string id_string = "";
    if (id.size() > 0) {
        id_string = "id=" + id + ", ";
    }
    
    string app = args.front();
    
    char date[32];
    iso2date(start, date, sizeof(date));
    
    char summary[2048];
    sprintf(summary, 
        "[cluster-task %sname=%s, start=\"%s\", duration=%.3f, "
        "status=%d, app=\"%s\", hostname=\"%s\", slot=%d, cpus=%u, memory=%u]\n",
        id_string.c_str(), name.c_str(), date, elapsed(), status, app.c_str(), 
        worker->host_name.c_str(), worker->rank, cpus, memory);
    
    write(worker->out, summary, strlen(summary));
}

bool TaskHandler::succeeded() {
    return status == 0;
}

void TaskHandler::execute() {
    log_trace("Running task %s", this->name.c_str());
    
    this->status = run_process();
    
    // If the task succeeded, then read all of the files. We only
    // do this if the task succeeded because we only send the data
    // if the task succeeded.
    if (this->succeeded()) {
        if (read_file_data()) {
            // If unable to read file data, then set the status
            // to exitcode = 1
            this->status = 256;
        }
    }
    
    // This needs to go after read_file_data because that method
    // may change the status of the task
    write_cluster_task();
    
    // Regardless of what happens, we need to delete the files
    delete_files();
    
    // If the task succeeded, then send the I/O back to the master.
    // We only do this if the task succeeds because if the task 
    // failed, then it might not have generated good output data.
    // It is important that we do this before sending back the 
    // result message. If we send the result message first, or if
    // it gets processed first, then we could have a situation
    // where, when a failure occurs, a task has been marked as
    // success in the transaction log, but the I/O from the task
    // has not been saved. The MPI standard guarantees that 
    // messages sent from one process to another are delivered 
    // in the order sent.
    if (this->succeeded()) {
        send_io_data();
    }
    
    send_result();
}

Worker::Worker(const string &outfile, const string &errfile, const string &host_script, unsigned int host_memory, unsigned host_cpus, bool strict_limits) {
    this->outfile = outfile;
    this->errfile = errfile;

    this->host_script = host_script;
    if (host_memory == 0) {
        // If host memory is not specified by the user, then get the amount
        // of physical memory on the host and convert it to MB. 1 MB is the 
        // minimum, but that shouldn't ever happen.
        unsigned long bytes = get_host_memory();
        this->host_memory = (unsigned)ceil(bytes / (1024.0*1024.0)); // bytes -> MB
    } else {
        this->host_memory = host_memory;
    }
    if (host_cpus == 0) {
        this->host_cpus = get_host_cpus();
    } else {
        this->host_cpus = host_cpus;
    }
    this->strict_limits = strict_limits;
    this->host_script_pgid = 0;
    MPI_Comm_rank(MPI_COMM_WORLD, &rank);
    get_host_name(host_name);
}

Worker::~Worker() {
}

/**
 * Launch the host script if a) this worker has host rank 0, and 
 * b) the host script is valid 
 */
void Worker::run_host_script() {
    // Only launch it if it exists
    if (host_script == "")
        return;
    
    // Only host_rank 0 launches a script, the others need to wait
    if (host_rank > 0)
        return;
    
    log_info("Worker %d: Launching host script %s", rank, host_script.c_str());
    
    pid_t pid = fork();
    if (pid < 0) {
        myfailures("Worker %d: Unable to fork host script", rank); 
    } else if (pid == 0) {
        // Redirect stdout to stderr
        if (dup2(STDERR_FILENO, STDOUT_FILENO) < 0) {
            log_fatal("Unable to redirect host script stdout to stderr: %s", 
                strerror(errno));
            exit(1);
        }
        
        // Create a new process group so we can kill it later if
        // it runs longer than the workflow
        if (setpgid(0, 0) < 0) {
            log_fatal("Unable to set process group in host script: %s", 
                strerror(errno));
            exit(1);
        }
        
        // Close any other open descriptors. This will not really close
        // everything, but it is unlikely that we will have more than a 
        // few descriptors open. It depends on MPI.
        for (int i=3; i<32; i++) {
            close(i);
        }
        
        // Exec process
        char *argv[2] = {
            (char *)host_script.c_str(),
            NULL
        };
        execvp(argv[0], argv);
        fprintf(stderr, "Unable to exec host script: %s\n", strerror(errno));
        exit(1);
    } else {
        
        // Also set process group here to avoid potential races. It is 
        // possible that we might try to call killpg() before the child
        // has a chance to run. Calling setpgid() here ensures that the
        // child's process group will always be set before killpg() is 
        // called so that it doesn't fail.
        if (setpgid(pid, pid) < 0) {
            log_error("Unable to set process group for host script: %s", 
                strerror(errno));
        }
        
        // Record the process group id so we can kill it when the workflow finishes
        host_script_pgid = pid;
        
        // Give this process a timeout
        struct sigaction act;
        struct sigaction oact;
        act.sa_handler = log_signal;
        act.sa_flags = SA_NODEFER;
        if (sigaction(SIGALRM, &act, &oact) < 0) {
            myfailures(
                "Worker %d: Unable to set signal handler for SIGALRM", rank);
        }
        alarm(HOST_SCRIPT_TIMEOUT);
        
        // Wait for the host script to exit
        int status; pid_t result = waitpid(pid, &status, 0);
        
        // Reset timer
        alarm(0);
        if (sigaction(SIGALRM, &oact, NULL) < 0) {
            myfailures(
                "Worker %d: Unable to clear signal handler for SIGALRM", rank);
        }
        
        if (result < 0) {
            if (errno == EINTR) {
                // If waitpid was interrupted, then the host script timed out
                // Kill the host script's process group
                killpg(pid, SIGKILL);
                myfailure("Worker %d: Host script timed out after %d seconds", 
                    rank, HOST_SCRIPT_TIMEOUT);
            } else {
                myfailures("Worker %d: Error waiting for host script", rank);
            }
        } else {
            if (WIFEXITED(status)) {
                log_info("Worker %d: Host script exited with status %d (%d)", 
                    rank, WEXITSTATUS(status), status);
            } else {
                log_info("Worker %d: Host script exited on signal %d (%d)", 
                    rank, WTERMSIG(status), status);
            }
            
            if (status != 0) {
                myfailure("Worker %d: Host script failed", rank);
            }
        }
    }
}

/**
 * Send SIGTERM to the host script's process group to shut down any services that
 * it left running.
 */
void Worker::kill_host_script_group() {
    // Workers with host_rank > 0 will not have host scripts
    if (host_rank > 0)
        return;
    
    // Not necessary if there is no pgid to kill
    if (host_script_pgid <= 0)
        return;
    
    log_debug("Worker %d: Terminating host script process group with SIGTERM", rank);
    
    if (killpg(host_script_pgid, SIGTERM) < 0) {
        if (errno != ESRCH) {
            log_warn("Worker %d: Unable to terminate host script process group: %s", 
                rank, strerror(errno));
        }
    } else {
        // There must have been some processes in the process group, give 
        // them a few seconds and then kill them
        if (sleep(HOST_SCRIPT_GRACE_PERIOD) != 0) {
            log_warn("Worker %d: sleep() finished prematurely", rank);
        }
        if (killpg(host_script_pgid, SIGKILL) < 0) {
            if (errno != ESRCH) {
                log_warn("Worker %d: Unable to kill host script process group: %s", 
                    rank, strerror(errno));
            }
        } else {
            // If the call didn't fail, then there were some remaining
            log_warn("Worker %d: Sent SIGKILL to resilient host script processes", rank);
        }
    }
}

int Worker::run() {
    log_debug("Worker %d: Starting...", rank);
    
    // Send worker's registration message to the master
    RegistrationMessage regmsg(host_name, host_memory, host_cpus);
    send_message(&regmsg, 0);
    log_trace("Worker %d: Host name: %s", rank, host_name.c_str());
    log_trace("Worker %d: Host memory: %u MB", rank, this->host_memory);
    log_trace("Worker %d: Host CPUs: %u", rank, this->host_cpus);
    
    // Get worker's host rank
    HostrankMessage *hrmsg = dynamic_cast<HostrankMessage *>(recv_message());
    if (hrmsg == NULL) {
        myfailure("Expected hostrank message");
    }
    host_rank = hrmsg->hostrank;
    delete hrmsg;
    log_trace("Worker %d: Host rank: %d", rank, host_rank);
    
    log_debug("Worker %d: Using task stdout file: %s", rank, outfile.c_str());
    log_debug("Worker %d: Using task stderr file: %s", rank, errfile.c_str());
    
    out = open(outfile.c_str(), O_WRONLY|O_APPEND|O_CREAT, 0000644);
    if (out < 0) {
        myfailures("Worker %d: unable to open task stdout", rank);
    }
    
    err = open(errfile.c_str(), O_WRONLY|O_APPEND|O_CREAT, 0000644);
    if (err < 0) {
        myfailures("Worker %d: unable to open task stderr", rank);
    }
    
    // If there is a host script, then run it and wait here for all the host scripts to finish
    if ("" != host_script) {
        run_host_script();
        MPI_Barrier(MPI_COMM_WORLD);
    }
    
    while (true) {
        log_trace("Worker %d: Waiting for request", rank);
        
#ifdef SLEEP_IF_NO_REQUEST
        /* On many MPI implementations MPI_Recv uses a busy wait loop. This
         * really wreaks havoc on the load and CPU utilization of the workers
         * when there are no tasks to process or some slots are idle due to 
         * limited resource availability (memory and CPUs). In order to avoid 
         * that we check here to see if there are any requests first, and if 
         * there are not, then we wait for a few millis before checking again 
         * and keep doing that until there is a request waiting. This should 
         * reduce the load/CPU usage on workers significantly. It decreases
         * responsiveness a bit, but it is a fair tradeoff.
         */
        while (!message_waiting()) {
            usleep(NO_MESSAGE_SLEEP_TIME);
        }
#endif
        
        Message *mesg = recv_message();
        if (ShutdownMessage *sdm = dynamic_cast<ShutdownMessage *>(mesg)) {
            log_trace("Worker %d: Got shutdown message", rank);
            delete sdm;
            break;
        } else if (CommandMessage *cmd = dynamic_cast<CommandMessage *>(mesg)) {
            
            log_trace("Worker %d: Got task", rank);
            
            TaskHandler task(this, cmd->name, cmd->command, 
                    cmd->id, cmd->memory, cmd->cpus, cmd->pipe_forwards,
                    cmd->file_forwards);
            
            task.execute();
        } else {
            myfailure("Unexpected message");
        }
        
        delete mesg;
    }
    
    kill_host_script_group();
    
    close(out);
    close(err);
    
    log_debug("Worker %d: Exiting...", rank);
    
    return 0;
}
