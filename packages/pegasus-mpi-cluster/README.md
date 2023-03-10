# This is a workflow engine that runs as an MPI job.

The workflows are simple DAGs (Directed Acyclic Graphs) described with a
file format similar to that used by Condor DAGMan. There are some example 
DAGs in the test directory. More information on the format can be found 
in the man page.

The MPI rank 0 process becomes a master, and the rank 1..N processes become
workers. The master process hands out the tasks to the workers in FCFS
order, according to the dependencies specified in the DAG.

To build the code run:

    $ make

If the system you are on does not have an 'mpicxx' wrapper for the C++
compiler then you will have to set CXX to point to the system equivalents. 
For example, to build on a Cray XT5 with the PGI compiler:

    $ make CXX=CC CXXFLAGS=""

To run the tests do:

    $ make test

Finally, to install do:

    $ make install

By default it will install in $(PEGASUS_HOME), otherwise you can do:

    $ make prefix=/usr/local install

To execute a workflow run:

    $ mpirun -n 4 pegasus-mpi-cluster test/diamond.dag

or something similar in your PBS/LSF/SGE submit script. Ask your local
system administrator if you are unsure how to run MPI applications on
your cluster.

For more information see the mpidag.1 man page.

## Warnings

### Integrity checking

The duration per job reported by `pegasus-mpi-cluster` includes integrity checking runtime (checksum files). 
Therefore, the duration by PMC **can be greater** than the duration reported by `kickstart` if integrity checking is enabled.


