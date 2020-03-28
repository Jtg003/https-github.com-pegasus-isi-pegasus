import logging
import re
import shutil
import subprocess
import time
from functools import partial
from os import path


def from_env(pegasus_home: str = None):
    if not pegasus_home:
        pegasus_version_path = shutil.which("pegasus-version")

        if not pegasus_version_path:
            raise ValueError("PEGASUS_HOME not found")

        pegasus_home = path.dirname(path.dirname(pegasus_version_path))

    return Client(pegasus_home)


class Client:
    """
    Pegasus client.

    Pegasus workflow management client.
    """

    def __init__(self, pegasus_home: str):
        self._log = logging.getLogger(__name__)
        self._pegasus_home = pegasus_home

        base = path.normpath(path.join(pegasus_home, "bin"))

        self._plan = path.join(base, "pegasus-plan")
        self._run = path.join(base, "pegasus-run")
        self._status = path.join(base, "pegasus-status")
        self._remove = path.join(base, "pegasus-remove")
        self._analyzer = path.join(base, "pegasus-analyzer")
        self._statistics = path.join(base, "pegasus-statistics")

    def plan(
        self,
        dax: str,
        conf: str = None,
        sites: str = "local",
        output_site: str = "local",
        input_dir: str = None,
        output_dir: str = None,
        dir: str = None,
        relative_dir: str = None,
        cleanup: str = "none",
        verbose: int = 0,
        force: bool = False,
        submit: bool = False,
        **kwargs
    ):
        cmd = [self._plan]

        for k, v in kwargs.items():
            cmd.append("-D{}={}".format(k, v))

        if conf:
            cmd.extend(("--conf", conf))

        if sites:
            cmd.extend(("--sites", sites))

        if output_site:
            cmd.extend(("--output-site", output_site))

        if input_dir:
            cmd.extend(("--input-dir", input_dir))

        if output_dir:
            cmd.extend(("--output-dir", output_dir))

        if dir:
            cmd.extend(("--dir", dir))

        if relative_dir:
            cmd.extend(("--relative-dir", relative_dir))

        if cleanup:
            cmd.extend(("--cleanup", cleanup))

        if verbose:
            cmd.append("-" + "v" * verbose)

        if force:
            cmd.append("--force")

        if submit:
            cmd.append("--submit")

        cmd.extend(("--dax", dax))

        rv = subprocess.run(cmd)

        if rv.returncode:
            self._log.fatal("Plan: {} \n {}".format(rv.stdout, rv.stderr))

        self._log.info("Plan: {} \n {}".format(rv.stdout, rv.stderr))

        submit_dir = self._get_submit_dir(rv.stdout)
        workflow = Workflow(submit_dir, self)
        return workflow

    def run(self, submit_dir: str, verbose: int = 0):
        cmd = [self._run]

        if verbose:
            cmd.append("-" + "v" * verbose)

        cmd.append(submit_dir)

        rv = subprocess.run(cmd)

        if rv.returncode:
            self._log.fatal("Run: {} \n {}".format(rv.stdout, rv.stderr))

        self._log.info("Run: {} \n {}".format(rv.stdout, rv.stderr))

    def status(self, submit_dir: str, long: bool = False, verbose: int = 0):
        cmd = [self._status]

        if long:
            cmd.append("--long")

        if verbose:
            cmd.append("-" + "v" * verbose)

        cmd.append(submit_dir)

        rv = subprocess.run(cmd)

        if rv.returncode:
            self._log.fatal("Status: {} \n {}".format(rv.stdout, rv.stderr))

        self._log.info("Status: {} \n {}".format(rv.stdout, rv.stderr))

    def wait(self, submit_dir: str, delay: int = 2):
        """Prints progress bar and blocks until workflow completes or fails"""

        # match output from pegasus-status
        # for example, given the following output:
        #
        # UNRDY READY   PRE  IN_Q  POST  DONE  FAIL %DONE STATE   DAGNAME
        #     0     0     0     0     0     8     0 100.0 Success *appends-0.dag
        #
        # the pattern would match the second line
        p = re.compile(r"\s*((\d+\s+){7})(\d+\.\d+\s+)(\w+\s+)(.*)")

        # indexes for info provided from status
        # UNRDY = 0
        READY = 1
        # PRE = 2
        IN_Q = 3
        # POST = 4
        DONE = 5
        FAIL = 6
        PCNT_DONE = 7
        STATE = 8

        # color strings for terminal output
        green = lambda s: "\x1b[1;32m" + s + "\x1b[0m"
        yellow = lambda s: "\x1b[1;33m" + s + "\x1b[0m"
        blue = lambda s: "\x1b[1;36m" + s + "\x1b[0m"
        red = lambda s: "\x1b[1;31m" + s + "\x1b[0m"

        while True:
            rv = subprocess.run(
                ["pegasus-status", "-l", submit_dir],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            if rv.returncode != 0:
                raise Exception(rv.stderr)

            for line in rv.stdout.decode("utf8").split("\n"):
                matched = p.match(line)

                if matched:
                    v = matched.group(1).split()
                    v.append(float(matched.group(3).strip()))
                    v.append(matched.group(4).strip())

                    completed = green("Completed: " + v[DONE])
                    queued = yellow("Queued: " + v[READY])
                    running = blue("Running: " + v[IN_Q])
                    fail = red("Failed: " + v[FAIL])

                    stats = (
                        "("
                        + completed
                        + ", "
                        + queued
                        + ", "
                        + running
                        + ", "
                        + fail
                        + ")"
                    )

                    # progress bar
                    bar_len = 50
                    filled_len = int(round(bar_len * (v[PCNT_DONE] * 0.01)))

                    bar = (
                        "\r["
                        + green("#" * filled_len)
                        + ("-" * (bar_len - filled_len))
                        + "] {percent:>5}% ..{state} {stats}".format(
                            percent=v[PCNT_DONE], state=v[STATE], stats=stats
                        )
                    )

                    if v[PCNT_DONE] < 100:
                        print(bar, end=("" if v[STATE] != "Failure" else "\n"))
                    else:
                        print(bar)

                    # skip the rest of the lines
                    break

            if v[PCNT_DONE] >= 100 or v[STATE] in {"Success", "Failure"}:
                break

            time.sleep(delay)

    def remove(self, submit_dir: str, verbose: int = 0):
        cmd = [self._remove]

        if verbose:
            cmd.append("-" + "v" * verbose)

        cmd.append(submit_dir)

        rv = subprocess.run(cmd)

        if rv.returncode:
            self._log.fatal("Remove: {} \n {}".format(rv.stdout, rv.stderr))

        self._log.info("Remove: {} \n {}".format(rv.stdout, rv.stderr))

    def analyzer(self, submit_dir: str, verbose: int = 0):
        cmd = [self._analyzer]

        if verbose:
            cmd.append("-" + "v" * verbose)

        cmd.append(submit_dir)

        rv = subprocess.run(cmd)

        if rv.returncode:
            self._log.fatal("Analyzer: {} \n {}".format(rv.stdout, rv.stderr))

        self._log.info("Analyzer: {} \n {}".format(rv.stdout, rv.stderr))

    def statistics(self, submit_dir: str, verbose: int = 0):
        cmd = [self._statistics]

        if verbose:
            cmd.append("-" + "v" * verbose)

        cmd.append(submit_dir)

        rv = subprocess.run(cmd)

        if rv.returncode:
            self._log.fatal("Statistics: {} \n {}".format(rv.stdout, rv.stderr))

        self._log.info("Statistics: {} \n {}".format(rv.stdout, rv.stderr))

    @staticmethod
    def _get_submit_dir(output: str):
        if not output:
            return

        # pegasus-plan produces slightly different output based on the presence
        # of the --submit flag, therefore we need to search for
        # pegasus-(run|remove) to get the submit directory
        pattern = re.compile(r"pegasus-(run|remove)\s*(.*)$")

        for line in output.splitlines():
            line = line.strip()
            match = pattern.search(line)

            if match:
                return match.group(2)


class Workflow:
    def __init__(self, submit_dir: str, client: Client = None):
        self._log = logging.getLogger(__name__)
        self._client = None
        self._submit_dir = submit_dir
        self.client = client or from_env()

        self.run = None
        self.status = None
        self.remove = None
        self.analyze = None
        self.statistics = None

    @property
    def client(self):
        return self._client

    @client.setter
    def client(self, client: Client):
        self._client = client

        self.run = partial(self._client.run, self._submit_dir)
        self.status = partial(self._client.status, self._submit_dir)
        self.remove = partial(self._client.remove, self._submit_dir)
        self.analyze = partial(self._client.analyzer, self._submit_dir)
        self.statistics = partial(self._client.statistics, self._submit_dir)