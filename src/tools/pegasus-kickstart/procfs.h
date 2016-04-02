#ifndef KICKSTART_PROCFS_H
#define KICKSTART_PROCFS_H

#include <unistd.h>
#include <time.h>
#include <netinet/in.h>

typedef struct _ProcStats {
    time_t ts;
    in_addr_t host;
    pid_t pid;
    pid_t ppid;
    unsigned int rank;
    unsigned long long rchar;
    unsigned long long wchar;
    unsigned long syscr;
    unsigned long syscw;
    unsigned long long read_bytes;
    unsigned long long write_bytes;
    unsigned long long cancelled_write_bytes;
    double utime;
    double stime;
    double iowait;
    unsigned long long vmpeak; /* peak vm size */
    unsigned long long vm; /* current VM size */
    unsigned long long rsspeak; /* peak RSS */
    unsigned long long rss; /* current RSS */
    unsigned int threads;
#ifdef HAS_PAPI
    long long PAPI_TOT_INS; /* Total instructions */
    long long PAPI_LD_INS; /* Load instructions */
    long long PAPI_SR_INS; /* Store instructions */
    long long PAPI_FP_INS; /* Floating point instructions */
    long long PAPI_FP_OPS; /* Floating point ops */
    long long PAPI_L3_TCM; /* L3 cache misses */
    long long PAPI_L2_TCM; /* L2 cache misses */
    long long PAPI_L1_TCM; /* L1 cache misses */
#endif
    char exe[127];
    char state; /* The current state of the process: 'X' is terminated. */
} ProcStats;

typedef struct _ProcStatsList {
    ProcStats stats;
    struct _ProcStatsList *next;
} ProcStatsList;

void procfs_stats_init(ProcStats *stats);
int procfs_read_stats(pid_t process, ProcStats *stats);
void procfs_read_stats_group(ProcStatsList **listptr);
void procfs_merge_stats_list(ProcStatsList *list, ProcStats *result, int interval);
void procfs_free_stats_list(ProcStatsList *list);
void procfs_update_list(ProcStatsList **listptr, ProcStats *stats);

#endif
