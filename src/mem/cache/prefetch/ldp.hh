/**
* Difference-based prefetcher
*/

#ifndef __MEM_CACHE_PREFETCH_DIFF_MATCHING_HH__
#define __MEM_CACHE_PREFETCH_DIFF_MATCHING_HH__

#include <vector>
#include <queue>
#include <unordered_map>
#include <utility>

#include "base/types.hh"
#include "mem/cache/prefetch/stride.hh"
#include "mem/cache/prefetch/queued.hh"
#include "sim/eventq.hh"

namespace gem5
{

struct LDPPrefetcherParams;

GEM5_DEPRECATED_NAMESPACE(Prefetcher, prefetch);
namespace prefetch
{

class LDP : public Stride
{

    typedef int64_t IndexData;
    typedef int64_t TargetAddr;

    static constexpr Addr MaxTrackedIndexPC = 0x415000;

    const int iddt_ent_num;
    const int tadt_ent_num;
    const int iq_ent_num;
    const int rg_ent_num;
    const int ics_ent_num;
    const int rt_ent_num;

    // indirect range prefetch length
    // int range_ahead_dist_level_1;
    // int range_ahead_dist_level_2;
    // int range_ahead_init_level_1;
    // int range_ahead_init_level_2;
    // int range_ahead_buffer_level_1;
    // int range_ahead_buffer_level_2;
    int indir_range;
    // Addr upper_400ca0;

    // int replace_count_level_2;
    // int replace_threshold_level_2;

    int notify_latency;

    // priority init
    int32_t cur_range_priority;
    int32_t range_group_size;
    int range_count;

    // possible shift values
    const unsigned int shift_v[6] = {0, 1, 2, 3, 4, 5};

    /** IDDT and TADT */
    const int iddt_diff_num;
    const int tadt_diff_num;
    const std::vector<Addr> pointer_type_addrs_hint;

    bool offsetfilter_enable;
    const int offsetfilter_th;
    bool link_detection_enable;
    unsigned range_indirect_lookahead_start;
    unsigned range_indirect_lookahead_span;
    unsigned range_indirect_lookahead_step;

    template <typename T>
    class DiffSeqCollection
    {
        Addr pc;
        bool valid;
        bool ready;
        bool is_pointer_chase;
        bool is_finish_pochase;
        bool is_early;
        bool found_pochase;
        ContextID cID;
        T last;
        T last_value;
        T pointer_offset;

        int diff_ptr;
        int tryPoChaseCnt;
        const int diff_size;
        std::vector<T> diff;

      public:

        // normal constructor
        DiffSeqCollection(Addr pc, T last, int diff_size)
          : pc(pc), valid(false), ready(false),is_pointer_chase(false),is_finish_pochase(false),is_early(false), found_pochase(false), cID(0), 
            last(last), last_value(-4096), pointer_offset(-1), diff_ptr(0), tryPoChaseCnt(0), diff_size(diff_size) 
        {
            diff.reserve(diff_size);
        };

        // init constructor
        DiffSeqCollection(int diff_size, bool valid = false)
         : pc(0), valid(valid), ready(false), is_pointer_chase(false),
           is_finish_pochase(false), is_early(false), found_pochase(false),
           cID(0), last(0), last_value(-4096), pointer_offset(-1),
           diff_ptr(0), tryPoChaseCnt(0), diff_size(diff_size)
        {
           diff.reserve(diff_size);
        };

        ~DiffSeqCollection() = default;

        void validate() { valid = true; };

        void invalidate ()
        {
            diff_ptr = 0;
            cID = 0;
            valid = false;
            diff.clear();
            tryPoChaseCnt = 0;
            pointer_offset = -1;
        };

        void fill (T last_in, ContextID cID_in)
        {
            if (cID_in != cID) return;

            if (ready) {
                diff[diff_ptr] = last_in - last;
                diff_ptr = (diff_ptr+1) % diff_size;
            } else {
                diff.push_back(last_in - last);
                if (diff.size() == diff_size) ready = true;
            }
            last = last_in;
        };

        void update_last_value(T last_in)
        {
            last_value=last_in;
        };
        
        void update_pointer_chase(T pointer_offset_in)
        {
            is_pointer_chase=true;
            pointer_offset = pointer_offset_in;
        };

        void update_finish()
        {
            is_finish_pochase=true;
        };

        void set_early()
        {
            is_early=true;
        };

        void clear_early()
        {
            is_early=false;
        };
        
        void set_found()
        {
            found_pochase=true; 
        }

        void add_cnt()
        {
            tryPoChaseCnt=tryPoChaseCnt+1; 
        }


        bool isReady() const { return ready; };

        bool isValid() const { return valid; };

        bool isEarly() const { return is_early; };

        bool isPointer() const {return is_pointer_chase;};

        bool isFinish() const {return is_finish_pochase;};

        bool foundPointer() const {return found_pochase;};

        Addr getPC() const { return pc; }; 
        
        int getCnt() const {return tryPoChaseCnt; };

        ContextID getContextId() const { return cID; };

        T getLast() const {return last; };

        T getValue() const {return last_value;};

        T operator[](int index) const { return diff[ (diff_ptr+index) % diff_size ]; };

        DiffSeqCollection& update(Addr pc_new, ContextID cID_new, T last_new = 0, bool is_earlyPo = false)
        {
            pc = pc_new;
            last = last_new;
            last_value=-4096;
            cID = cID_new;
            ready = false;
            valid = false;
            is_pointer_chase=false;
            is_finish_pochase=false;
            is_early=is_earlyPo;
            found_pochase=false;
            diff_ptr = 0;
            tryPoChaseCnt = 0;
            diff.clear();
            return *this;
        };
    };

    typedef DiffSeqCollection<IndexData> iddt_ent_t;
    typedef DiffSeqCollection<TargetAddr> tadt_ent_t;

    std::vector<iddt_ent_t> indexDataDeltaTable;
    std::vector<tadt_ent_t> targetAddrDeltaTable;

    int iddt_ptr;
    int tadt_ptr;

    void insertIDDT(Addr index_pc_in, ContextID cID_in, bool is_earlyPo);
    void insertTADT(Addr target_pc_in, ContextID cID_in , bool is_earlyPo);
    bool offsetFilter(tadt_ent_t& tadt_ent,Addr req_addr);
    /** RangeTable related */

    /** Range quantification method
    * eg. unit=8, level=4
    * level:   |  1  |  2  |  3  |  4  |
    * unti:    |  u  |  u  |  u  |  u  |
    * range:   0     8     16    24    32 
    */
    // const int range_unit_param; // quantify true range to several units
    // const int range_level_param; // total levels of range quant unit 
    // const int range_active_threshold; // total levels of range quant unit 

    struct RangeTableEntry
    {
        Addr target_pc; // range base on req address
        Addr cur_tail[2];
        int cur_count;
        ContextID cID;
        bool valid;

        int shift_times; // 0 (byte) / 2 (int) / 3 (double)
        
        const int range_quant_unit; // quantify true range to several units
        const int range_quant_level; // total levels of range quant unit 
        const int range_active_th; // if the sum of sample count over this value the pc is range_type

        // NOTE: Range prefetch distance should cooperate wit StreamPrefetch
        // NOTE: [TODO] more suitable RangePrefetch schedule policy
        std::vector<int> sample_count;

        // normal constructor
        RangeTableEntry(
                Addr target_pc, Addr req_addr, int shift_times, int rql, int rqu , int rat
            ) : target_pc(target_pc), cur_tail{req_addr, MaxAddr}, 
                cur_count(0), cID(0), valid(false), shift_times(shift_times), 
                range_quant_unit(rqu), range_quant_level(rql),range_active_th(rat), 
                sample_count(rql) {}

        // init constructor
        RangeTableEntry(int rqu, int rql, int rat, bool valid = false)
          : target_pc(0), cur_tail{0, MaxAddr}, cur_count(0), cID(0),
            valid(valid), shift_times(0), range_quant_unit(rqu),
            range_quant_level(rql), range_active_th(rat), sample_count(rql) {};

        ~RangeTableEntry() = default;

        bool updateSample(Addr addr_in); 

        void validate() { valid = true; };

        void invalidate() { 
            valid = false; 
            std::fill(sample_count.begin(), sample_count.end(), 0); 
        };
        
        bool getRangeType() const;

        RangeTableEntry& update(
            Addr target_pc_in,
            Addr req_addr_in,
            int shift_times_in,
            ContextID cID_in
        ) {
            target_pc = target_pc_in;
            cur_tail[0] =  req_addr_in;
            cur_tail[1] = MaxAddr;
            cur_count = 0;
            cID = cID_in;
            valid = false;
            shift_times = shift_times_in;
            std::fill(sample_count.begin(), sample_count.end(), 0); 
            return *this;
        }
    };

    std::vector<RangeTableEntry> rangeTable;

    int rg_ptr;

    void insertRG(Addr req_addr_in, Addr target_pc_in, ContextID cID_in);

    bool rangeFilter(Addr pc_in, Addr addr_in, ContextID cID_in);


    /** IndexQueue related */
    struct IndexQueueEntry
    {
        Addr index_pc;
        ContextID cID;
        bool valid;
        int tried;
        int matched;

        // normal constructor
        IndexQueueEntry(Addr pc_in) 
          : index_pc(pc_in), cID(0), valid(false), 
            tried(0), matched(0) {};

        // init constructor
        IndexQueueEntry(bool valid = false)
          : index_pc(0), cID(0), valid(valid), tried(0), matched(0) {};

        ~IndexQueueEntry() = default;

        float getWeight() const { return (matched + 1) / (tried + 1e-8); };

        void validate() { valid = true; };

        void invalidate() { valid = false; };

        IndexQueueEntry& update(Addr index_pc_in, ContextID cID_in) {
            index_pc = index_pc_in;
            cID = cID_in;
            valid = false;
            tried = 0;
            matched = 0;
            return *this;
        };
    };
    std::vector<IndexQueueEntry> indexQueue;

    int iq_ptr;

    // TODO: insert from Stride Hit
    void insertIndexQueue(Addr index_pc, ContextID cID_in, bool linkedFlag = false);

    void pickIndexPC();

    void matchUpdate(Addr index_pc_in, Addr target_pc_in, ContextID cID_in);


    /** IndirectCandidateScoreboard related*/
    struct ICSEntry
    {
        Addr index_pc;
        ContextID cID;
        int candidate_num;
        bool valid;

        std::unordered_map<Addr, int> miss_count;

        // normal constructor
        ICSEntry(Addr index_pc)
          : index_pc(index_pc), cID(0), candidate_num(0), valid(false) {};

        // init constructor
        ICSEntry(int candidate_num, bool valid = false)
         : index_pc(0), cID(0), candidate_num(candidate_num), valid(valid) {};

        ~ICSEntry() = default;

        void validate() { valid = true; };

        void invalidate() { valid = false; };

        bool updateMiss (Addr miss_pc, int miss_thred);

        ICSEntry& update(Addr index_pc_in, ContextID cID_in) {
            index_pc = index_pc_in;
            cID = cID_in;
            valid = false;
            miss_count.clear();
            return *this;
        };
    };
    std::vector<ICSEntry> indirectCandidateScoreboard;

    int ics_ptr;

    void notifyICSMiss(Addr miss_addr, Addr miss_pc_in, ContextID cID_in);

    void insertICS(Addr index_pc_in, ContextID cID_in);


    EventFunctionWrapper checkNewIndexEvent;

    bool auto_detect;
    const bool detect_only;
    const bool disable_iddt_tadt_init;

    int detect_period;

    int ics_miss_threshold;

    int ics_candidate_num;

    /** RelationTable related */
    struct RTEntry
    {
        Addr index_pc;
        Addr target_pc;
        Addr target_base_addr;
        unsigned int shift;
        bool range;
        int range_degree;
        ContextID cID;
        bool valid;
        bool is_pointer;
        bool key_relation;
        int32_t priority;

        // normal constructor
        RTEntry(
            Addr index_pc, Addr target_pc, Addr target_base_addr, 
            unsigned int shift, bool range, int range_degree, 
            ContextID cID, int32_t priority
        ) : index_pc(index_pc), target_pc(target_pc), target_base_addr(target_base_addr),
            shift(shift), range(range), range_degree(range_degree), cID(cID), valid(false),is_pointer(false),
            key_relation(false), priority(priority)
            {}

        // default constructor
        RTEntry(bool valid = false)
          : index_pc(0), target_pc(0), target_base_addr(0), shift(0),
            range(false), range_degree(0), cID(0), valid(valid),
            is_pointer(false), key_relation(false), priority(0) {};

        void validate() { 
            valid = true;
        };

        void invalidate() { 
            valid = false; 
        };

        bool isPointer() {return is_pointer;};
        // update for new relation
        RTEntry& update(
            Addr index_pc_in,
            Addr target_pc_in,
            Addr target_base_addr_in,
            unsigned int shift_in,
            bool range_in,
            int range_degree_in,
            ContextID cID_in,
            bool valid_in,
            bool is_pointer_in,
            bool key_relation_in,
            int32_t priority_in
        ) {
            index_pc = index_pc_in;
            target_pc = target_pc_in;
            target_base_addr = target_base_addr_in;
            shift = shift_in;
            range = range_in;
            range_degree = range_degree_in;
            cID = cID_in;
            valid = valid_in;
            is_pointer = is_pointer_in;
            key_relation = key_relation_in;
            priority = priority_in;
            return *this;
        };
    };
    std::vector<RTEntry> relationTable;
    // Pointer-chasing relations can contain cycles.  This guard prevents
    // recursive notifyFill() calls from overflowing the simulator stack.
    unsigned notifyFillDepth = 0;

    // point to the next update position
    int rt_ptr; 

    int findRTE(Addr index_pc, tadt_ent_t& tadt_ent_match, ContextID cID);

    void insertRT(
        iddt_ent_t& iddt_ent_match, tadt_ent_t& tadt_ent_match,
        int iddt_match_point, unsigned int shift, ContextID cID
    );

    void insertRTEntry(
        Addr index_pc,
        Addr target_pc,
        Addr target_base_addr,
        unsigned int shift,
        ContextID cID,
        bool range_type,
        bool is_pointer,
        bool key_relation
    );

    // return priority if target pc matched 
    int32_t getPriority(Addr target_pc_in, ContextID cID_in);

    // update priority for the entries in relationTable
    void updatePriority(Addr target_pc_in, int32_t priority_in, std::vector<uint8_t>& rt_bitmap);

    // return priority if range index pc matched, -1 for single pattern
    int32_t getRangeType(Addr index_pc_in, ContextID cID_in);

    /** LDP specific stats */
    struct LDPStats : public statistics::Group
    {
        LDPStats(statistics::Group *parent);
        void regStatsPerPC(const std::vector<Addr>& PC_list);

        // STATS
        statistics::Scalar ldp_pfIdentified;
        statistics::Vector ldp_pfIdentifiedPerPfPC;
        statistics::Scalar ldp_noValidData;
        statistics::Vector ldp_noValidDataPerPC;
        statistics::Scalar ldp_dataFill;
    } statsLDP;

    std::vector<Addr> ldp_stats_pc;

    // A StridePrefetcher which helps LDP detection.
    Stride* pf_helper;

    /** LDP functions */

  protected:

    void diffMatching(tadt_ent_t& tadt_ent);

    void callReadytoIssue(const PrefetchInfo& pfi, bool linkedFlag) override;

  public:
    LDP(const LDPPrefetcherParams &p);
    ~LDP();

    // Base notify for Cache access (Hit or Miss)
    void notify(const PacketPtr &pkt, const PrefetchInfo &pfi) override;

    // Probe DataResp from Memory for prefetch generation
    // void notifyFill(const PacketPtr &pkt, const uint8_t* data_ptr) override;
    void notifyFill(const PacketPtr &pkt, const u_int8_t* data_ptr, bool pointer_follow, Addr pointer_follow_pc, int pointer_offset) override;

    // Probe AddrReq to L1 for prefetch detection
    void notifyL1Req(const PacketPtr &pkt) override;
    // Probe DataResp from L1 for prefetch detection
    void notifyL1Resp(const PacketPtr &pkt) override;

    void insertIndirectPrefetch(Addr pf_addr, Addr target_pc, 
                                ContextID cID, int32_t priority,
                                bool is_pointer);

    void hitTrigger(const PacketPtr &pkt, Addr addr, const uint8_t* data_ptr, bool from_access) override;

    void addPfHelper(Stride* s);

    void calculatePrefetch(const PrefetchInfo &pfi,
                           std::vector<AddrPriority> &addresses,
                           const PacketPtr &pkt) override;
};

} // namespace prefetch
} // namespace gem5

#endif // __MEM_CACHE_PREFETCH_DIFF_MATCHING_HH__
