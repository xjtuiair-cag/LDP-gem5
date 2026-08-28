#include "mem/cache/prefetch/ldp.hh"
#include "base/trace.hh"
#include "mem/cache/mshr.hh"
#include "mem/cache/base.hh"

#include "debug/HWPrefetch.hh"
#include "debug/LDP.hh"
#include "debug/POINTER.hh"
#include "params/LDPPrefetcher.hh"
#include <algorithm>
#include <cstdint>
#include <exception>
#include <fstream>
#include <iterator>

namespace gem5
{

GEM5_DEPRECATED_NAMESPACE(Prefetcher, prefetch);
namespace prefetch
{



LDP::LDP(const LDPPrefetcherParams &p)
    : Stride(p),
    iddt_ent_num(p.iddt_ent_num),
    tadt_ent_num(p.tadt_ent_num),
    iq_ent_num(p.iq_ent_num),
    rg_ent_num(p.rg_ent_num),
    ics_ent_num(p.ics_ent_num),
    rt_ent_num(p.rt_ent_num),
    indir_range(p.indir_range),
    notify_latency(p.notify_latency),
    cur_range_priority(0),
    range_group_size(p.range_group_size),
    range_count(0),
    iddt_diff_num(p.iddt_diff_num),
    tadt_diff_num(p.tadt_diff_num),
    pointer_type_addrs_hint(p.pointer_pc_init),
    offsetfilter_enable(p.offsetfilter_enable),
    offsetfilter_th(p.offsetfilter_th),
    link_detection_enable(p.link_detection_enable),
    range_indirect_lookahead_start(p.range_indirect_lookahead_start),
    range_indirect_lookahead_span(p.range_indirect_lookahead_span),
    range_indirect_lookahead_step(p.range_indirect_lookahead_step),
    indexDataDeltaTable(p.iddt_ent_num, iddt_ent_t(p.iddt_diff_num, false)),
    targetAddrDeltaTable(p.tadt_ent_num, tadt_ent_t(p.tadt_diff_num, false)),
    iddt_ptr(0), tadt_ptr(0),
    // range_unit_param(p.range_unit),
    // range_level_param(p.range_level),
    // range_active_threshold(p.range_active_threshold),
    rangeTable(p.rg_ent_num * 6, RangeTableEntry(p.range_unit, p.range_level, p.range_active_threshold, false)),
    rg_ptr(0),
    indexQueue(p.iq_ent_num),
    iq_ptr(0),
    indirectCandidateScoreboard(p.ics_ent_num, ICSEntry(p.ics_candidate_num, false)),
    ics_ptr(0),
    checkNewIndexEvent([this] { pickIndexPC(); }, this->name()),
    auto_detect(p.auto_detect),
    detect_only(p.detect_only),
    disable_iddt_tadt_init(!p.rt_entry_init.empty()),
    detect_period(p.detect_period),
    ics_miss_threshold(p.ics_miss_threshold),
    ics_candidate_num(p.ics_candidate_num),
    relationTable(p.rt_ent_num),
    rt_ptr(0),
    statsLDP(this),
    ldp_stats_pc(p.stats_pc_list),
    pf_helper(nullptr)
{
    /**
     * Priority Update Policy:
     * new range-type priority = cur.priority - range_group_size
     * new single-type priority = parent_rte.priority + 1
     */


    cur_range_priority = std::numeric_limits<int32_t>::max()>>1;
    cur_range_priority -= cur_range_priority % range_group_size;



    if (!p.auto_detect) {
        /**
         * Manual Mode
         */
        std::vector<Addr> pc_list;

        if (!disable_iddt_tadt_init) {
            DPRINTF(LDP, "[GIVEN_IRT] Disable IDDT|TADT and auto detect. Injecting IRT\n");

            if (!p.index_pc_init.empty()) {
                for (auto index_pc : p.index_pc_init) {
                    auto& ent = indexDataDeltaTable[iddt_ptr];
                    ent.update(index_pc, 0, 0).validate();
                    iddt_ptr++;
                }
                pc_list.insert(
                    pc_list.end(), p.index_pc_init.begin(), p.index_pc_init.end()
                );
            }


            if (!p.target_pc_init.empty()) {
                for (auto target_pc : p.target_pc_init) {
                    targetAddrDeltaTable[tadt_ptr].update(target_pc, 0, 0).validate();
                    tadt_ptr++;
                }
                pc_list.insert(
                    pc_list.end(), p.target_pc_init.begin(), p.target_pc_init.end()
                );
            }


            if (!p.range_pc_init.empty()) {
                for (auto range_pc : p.range_pc_init) {
                    for (unsigned int shift_try: shift_v) {
                        rangeTable[rg_ptr].update(range_pc, 0x0, shift_try, 0).validate();
                        rg_ptr++;
                    }
                }
            }
        } else {
            DPRINTF(LDP, "rt_entry_init enabled: disable IDDT/TADT candidate initialization.\n");
        }



        //   [idx_pc, tgt_pc, tgt_base_addr, shift] × N

        if (!p.rt_entry_init.empty()) {
            const auto& re = p.rt_entry_init;
            size_t entry_len = 0;
            if (re.size() % 6 == 0) {
                entry_len = 6;
            } else if (re.size() % 4 == 0) {
                entry_len = 4;
            }
            fatal_if(entry_len == 0,
                "rt_entry_init length (%zu) must be a multiple of 4 or 6.",
                re.size());

            for (size_t i = 0; i + (entry_len - 1) < re.size(); i += entry_len) {
                Addr idx_pc = re[i];
                Addr tgt_pc = re[i + 1];
                Addr tgt_base = re[i + 2];
                unsigned shift = static_cast<unsigned>(re[i + 3]);
                bool is_range = false;
                bool is_ptr = (idx_pc == tgt_pc);

                if (entry_len == 6) {
                    is_range = (re[i + 4] != 0);
                    is_ptr = (re[i + 5] != 0);
                }
                if (std::find(
                        pointer_type_addrs_hint.begin(),
                        pointer_type_addrs_hint.end(),
                        idx_pc) != pointer_type_addrs_hint.end()) {
                    is_ptr = true;
                }

                insertRTEntry(
                    idx_pc, tgt_pc, tgt_base, shift, 0,
                    is_range, is_ptr, (is_range || is_ptr));
                pc_list.push_back(idx_pc);
                pc_list.push_back(tgt_pc);
            }
        }

        std::sort( pc_list.begin(), pc_list.end() );
        pc_list.erase( std::unique( pc_list.begin(), pc_list.end() ), pc_list.end() );


        statsLDP.regStatsPerPC(pc_list);
        ldp_stats_pc = pc_list;
    } else {
        statsLDP.regStatsPerPC(ldp_stats_pc);
    }
}

LDP::~LDP()
{
}



LDP::LDPStats::LDPStats(statistics::Group *parent)
    : statistics::Group(parent),
    ADD_STAT(ldp_pfIdentified, statistics::units::Count::get(),
             "number of LDP prefetch candidates identified"),
    ADD_STAT(ldp_pfIdentifiedPerPfPC, statistics::units::Count::get(),
             "number of LDP prefetch candidates identified per prefetch candidate"),
    ADD_STAT(ldp_noValidDataPerPC, statistics::units::Count::get(),
             "number of prefetch candidates without valid data per prefetch candidate"),
    ADD_STAT(ldp_dataFill, statistics::units::Count::get(),
             "number of LDP prefetch candidates identified")
{
    using namespace statistics;

    int max_per_pc = 32;


    ldp_pfIdentifiedPerPfPC
        .init(max_per_pc)
        .flags(total | nozero | nonan)
        ;

    ldp_noValidDataPerPC
        .init(max_per_pc)
        .flags(total | nozero | nonan)
        ;
}




void LDP::LDPStats::regStatsPerPC(const std::vector<Addr>& stats_pc_list)
{

    using namespace statistics;


    int max_per_pc = 32;

    assert(stats_pc_list.size() < max_per_pc);


    for (int i = 0; i < stats_pc_list.size(); i++) {

        std::stringstream stream;
        stream << std::hex << stats_pc_list[i];
        std::string pc_name = stream.str();


        ldp_pfIdentifiedPerPfPC.subname(i, pc_name);
        ldp_noValidDataPerPC.subname(i, pc_name);
    }
}


void LDP::pickIndexPC()
{

    float cur_weight = std::numeric_limits<float>::min();

    IndexQueueEntry* choosed_ent = nullptr;


    for (auto& iq_ent : indexQueue) {

        if (!iq_ent.valid) continue;


        float try_weight = iq_ent.getWeight();

        if (try_weight > cur_weight) {
            cur_weight = try_weight;
            choosed_ent = &iq_ent;
        }
    }


    if (choosed_ent != nullptr) {

        choosed_ent->tried++;

        insertICS(choosed_ent->index_pc, choosed_ent->cID);

        insertIDDT(choosed_ent->index_pc, choosed_ent->cID, false);


        DPRINTF(
            LDP, "pick for ICS: indexPC %llx cID %d\n",
            choosed_ent->index_pc, choosed_ent->cID
        );
    }


    if (auto_detect) {

        schedule(checkNewIndexEvent, curTick() + clockPeriod() * detect_period);
    }
}


//



//




void LDP::matchUpdate(Addr index_pc_in, Addr target_pc_in, ContextID cID_in)
{

    for (auto& iq_ent : indexQueue) {
        if (!iq_ent.valid) continue;
        if (iq_ent.index_pc == index_pc_in && iq_ent.cID == cID_in) {
            iq_ent.matched++;
            break;
        }
    }


    insertIndexQueue(target_pc_in, cID_in, false);
}

bool LDP::ICSEntry::updateMiss(Addr miss_pc, int miss_thred)
{

    auto candidate = miss_count.find(miss_pc);


    if (candidate != miss_count.end()) {


        if (candidate->second >= miss_thred) {

            return true;
        } else {

            candidate->second++;
        }

    } else if (miss_count.size() < candidate_num) {

        miss_count.insert({miss_pc, 0});
    }


    return false;
}


void LDP::notifyICSMiss(Addr miss_addr, Addr miss_pc_in, ContextID cID_in)
{

    for (auto& ics_ent : indirectCandidateScoreboard) {

        if (!ics_ent.valid) continue;


        if (ics_ent.cID != cID_in) continue;


        DPRINTF(LDP, "ICS updateMiss: targetPC %llx Addr %llx cID %d\n", miss_pc_in, miss_addr, cID_in);


        if (ics_ent.updateMiss(miss_pc_in, ics_miss_threshold)) {


            insertTADT(miss_pc_in, cID_in, false);
            insertRG(miss_addr, miss_pc_in, cID_in);


            DPRINTF(LDP, "ICS select: targetPC %llx cID %d\n", miss_pc_in, cID_in);


            return;
        }
    }
}

void
LDP::insertIndexQueue(Addr index_pc_in, ContextID cID_in, bool linkedFlag)
{

    if (index_pc_in > MaxTrackedIndexPC)
    {
        return;
    }

    // check if already exist
    for (auto& iq_ent : indexQueue) {

        if (!iq_ent.valid) continue;

        if (iq_ent.index_pc == index_pc_in && iq_ent.cID == cID_in) {
            if(linkedFlag){
                insertIDDT(index_pc_in, cID_in, true);
                insertTADT(index_pc_in, cID_in, true); //early version
                DPRINTF(LDP, "insert indexQueue caused by linkedlist: indexPC %llx cID %d by update %llx\n", index_pc_in, cID_in,indexQueue[iq_ptr].index_pc);
            };
            return;
        }
    }

    if(linkedFlag){
        DPRINTF(LDP, "insert indexQueue caused by linkedlist: indexPC %llx cID %d by replace %llx\n", index_pc_in, cID_in,indexQueue[iq_ptr].index_pc);
        insertIDDT(index_pc_in, cID_in, true);
        insertTADT(index_pc_in, cID_in, true); //early version
    } else {
        DPRINTF(LDP, "insert indexQueue: indexPC %llx cID %d by replace %llx\n", index_pc_in, cID_in ,indexQueue[iq_ptr].index_pc);
    }

    // insert to position iq_ptr
    indexQueue[iq_ptr].update(index_pc_in, cID_in).validate();
    iq_ptr = (iq_ptr + 1) % iq_ent_num;
}

void
LDP::insertICS(Addr index_pc_in, ContextID cID_in)
{

    if ((index_pc_in & 0xffff800000000000) != 0)
    {
        return;
    }

    // check if already exist
    for (auto& ics_ent : indirectCandidateScoreboard) {

        if (!ics_ent.valid) continue;

        if (ics_ent.index_pc == index_pc_in && ics_ent.cID == cID_in) return;
    }

    // insert to position ics_ptr
    indirectCandidateScoreboard[ics_ptr].update(index_pc_in, cID_in).validate();
    ics_ptr = (ics_ptr + 1) % ics_ent_num;

    DPRINTF(LDP, "insert ICS: indexPC %llx cID %d\n", index_pc_in, cID_in);
}

void
LDP::insertIDDT(Addr index_pc_in, ContextID cID_in, bool is_earlyPo)
{
    if (disable_iddt_tadt_init) {
        return;
    }

    if (index_pc_in > MaxTrackedIndexPC)
    {
        return;
    }

    //if (index_pc_in == 0x402104)
    //{
    //    return;
    //}

    // check if already exist
    for (auto& iddt_ent : indexDataDeltaTable) {

        if (!iddt_ent.isValid()) continue;

        if (iddt_ent.getPC() == index_pc_in && iddt_ent.getContextId() == cID_in) {
            if(!iddt_ent.foundPointer() && is_earlyPo){
                iddt_ent.set_early();
            }
            return;
        }

    }

    int iddr_ptr_rcd = iddt_ptr; //avoid dead-loop
    while (indexDataDeltaTable[iddt_ptr].isValid() &&
           (indexDataDeltaTable[iddt_ptr].isEarly() || indexDataDeltaTable[iddt_ptr].foundPointer())){
       iddt_ptr = (iddt_ptr + 1) % iddt_ent_num;
       if (iddt_ptr == iddr_ptr_rcd) {
            break; //avoid dead-loop
       }
    }

    if(is_earlyPo) {
        DPRINTF(LDP, "insert IDDT: indexPC %llx cID %d is early pointer by replace %llx\n", index_pc_in, cID_in, indexDataDeltaTable[iddt_ptr].getPC());
    } else {
        DPRINTF(LDP, "insert IDDT: indexPC %llx cID %d by replace %llx\n", index_pc_in, cID_in, indexDataDeltaTable[iddt_ptr].getPC());
    }
    // insert to position iddt_ptr
    indexDataDeltaTable[iddt_ptr].update(index_pc_in, cID_in,0,is_earlyPo).validate();
    iddt_ptr = (iddt_ptr + 1) % iddt_ent_num;

}

void
LDP::insertTADT(Addr target_pc_in, ContextID cID_in, bool is_earlyPo)
{
    if (disable_iddt_tadt_init) {
        return;
    }

    if ((target_pc_in & 0xffff800000000000) != 0)
    {
        return;
    }

    // check if already exist
    for (auto& tadt_ent : targetAddrDeltaTable) {

        if (!tadt_ent.isValid()) continue;

        if (tadt_ent.getPC() == target_pc_in && tadt_ent.getContextId() == cID_in) {
            DPRINTF(LDP, "insert TADT: targetPC %llx cID %d found \n", target_pc_in, cID_in);
            if (!tadt_ent.foundPointer() && is_earlyPo) {
                tadt_ent.set_early();
            }
            return;
        }
    }

    int tadt_ptr_rcd = tadt_ptr; //avoid dead-loop
    while (targetAddrDeltaTable[tadt_ptr].isValid() &&
           (targetAddrDeltaTable[tadt_ptr].isEarly() || targetAddrDeltaTable[tadt_ptr].foundPointer())){
       tadt_ptr = (tadt_ptr + 1) % tadt_ent_num;
       if (tadt_ptr == tadt_ptr_rcd) {
            break; //avoid dead-loop
       }
    }

    if(is_earlyPo) {
        DPRINTF(LDP, "insert TADT: targetPC %llx cID %d is early pointer by replace %llx\n", target_pc_in, cID_in, targetAddrDeltaTable[tadt_ptr].getPC());
    } else {
        DPRINTF(LDP, "insert TADT: targetPC %llx cID %d by replace %llx\n", target_pc_in, cID_in, targetAddrDeltaTable[tadt_ptr].getPC());
    }

    // insert to position tadt_ptr
    targetAddrDeltaTable[tadt_ptr].update(target_pc_in, cID_in, 0, is_earlyPo).validate();
    tadt_ptr = (tadt_ptr + 1) % tadt_ent_num;
}

void
LDP::insertRG(Addr req_addr_in, Addr target_pc_in, ContextID cID_in)
{

    if ((target_pc_in & 0xffff800000000000) != 0)
    {
        return;
    }

    // check if already exist
    for (auto& rg_ent : rangeTable) {

        if (!rg_ent.valid) continue;

        if (rg_ent.target_pc == target_pc_in && rg_ent.cID == cID_in) return;
    }

    // insert 6 rangeTableRntry for different shift values
    for (auto shift_try : shift_v) {
        rangeTable[rg_ptr].update(
            target_pc_in, req_addr_in, shift_try, cID_in
        ).validate();
        rg_ptr = (rg_ptr+1) % (rg_ent_num * 6);
    }

    DPRINTF(LDP, "insert RG: targetPC %llx cID %d\n", target_pc_in, cID_in);
}

void
LDP::diffMatching(tadt_ent_t& tadt_ent)
{
    // ready flag check
    assert(tadt_ent.isValid() && tadt_ent.isReady());

    // if((tadt_ent.getPC() & 0x7fbf000000)!=0)
    //     return;
    ContextID tadt_ent_cID = tadt_ent.getContextId();

    // try to match all valid and ready index data diff-sequence
    for (auto& iddt_ent : indexDataDeltaTable) {
        if (!iddt_ent.isValid() || !iddt_ent.isReady()) continue;
        if (tadt_ent_cID != iddt_ent.getContextId()) continue;

        if(tadt_ent.isFinish())
            DPRINTF(LDP, "diffmatching finish target PC %llx index PC %llx\n", tadt_ent.getPC(), iddt_ent.getPC());
        else
            DPRINTF(LDP, "diffmatching target PC %llx index PC %llx\n", tadt_ent.getPC(), iddt_ent.getPC());

        // a specific index data diff-sequence may have multiple matching point
        for (int i_start = 0; i_start < iddt_diff_num-tadt_diff_num+1; i_start++) {
            bool tryPoChase = false;
            // try different shift values
            for (unsigned int shift_try: shift_v) {
                int t_start = 0;
                bool all_same = true;
                int64_t last_iddt_data= 0;
                while (t_start < tadt_diff_num) {
                    if (iddt_ent[i_start+t_start] != (tadt_ent[t_start] >> shift_try)) {
                        break;
                    }
                    if(t_start > 0){
                        all_same = all_same && (last_iddt_data == iddt_ent[i_start+t_start]);
                    }
                    last_iddt_data = iddt_ent[i_start+t_start];
                    t_start++;
                    // DPRINTF(LDP, "diffmatching target PC %llx index PC %llx t_start %d\n",
                    // tadt_ent.getPC(), iddt_ent.getPC(),t_start);
                }

                if (t_start == tadt_diff_num) {
                    // match success
                    // insert pattern to RelationTable
                    if(all_same && i_start != iddt_diff_num-tadt_diff_num){
                        DPRINTF(LDP, "diffmatching match all same, skip insert RT target PC %llx index PC %llx i_start %d shift_try %d\n", tadt_ent.getPC(), iddt_ent.getPC(), i_start, shift_try);
                        break;
                    }

                    DPRINTF(LDP, "diffmatching match success try insert RT target PC %llx index PC %llx i_start %d shift_try %d\n", tadt_ent.getPC(), iddt_ent.getPC(), i_start, shift_try);

                    insertRT(iddt_ent, tadt_ent, i_start+tadt_diff_num, shift_try, tadt_ent_cID);

                    tryPoChase =  tryPoChase || true;
                    // match updata
                    // matchUpdate(iddt_ent.getPC(), tadt_ent.getPC(), tadt_ent.getContextId());
                }
            }
            if (!tryPoChase && (iddt_ent.getPC() == tadt_ent.getPC())) {
                iddt_ent.add_cnt();
                if(iddt_ent.getCnt() >2){
                   iddt_ent.clear_early();
                }
            }
        }

    }
}

int LDP::findRTE(Addr index_pc, tadt_ent_t& tadt_ent_match, ContextID cID)
{





    Addr target_pc = tadt_ent_match.getPC();


    for (int i = 0; i < rt_ent_num; i++)
    {
        auto& rte = relationTable[i];

        if (!rte.valid) continue;



        if (rte.index_pc == target_pc && rte.target_pc == index_pc && rte.cID == cID) {
            return -1;
        }





        if (rte.target_pc == target_pc && rte.cID == cID) {
            if((!rte.is_pointer)&&tadt_ent_match.isPointer())
            {
                DPRINTF(LDP, "findRTE: pointer update IndexPC %llx TargetPC %llx\n", rte.index_pc, rte.target_pc);
                rte.is_pointer = true;
            }
            if (rte.index_pc == index_pc)
            {
                // return -1;
                return i;
            }
            if (tadt_ent_match.isFinish())
                continue;// return true;
        }
    }

    return -2;
}

void
LDP::insertRTEntry(
    Addr new_index_pc,
    Addr new_target_pc,
    Addr target_base_addr,
    unsigned int shift,
    ContextID cID,
    bool new_range_type,
    bool is_pointer_in,
    bool key_relation)
{
    /* get priority */
    int32_t priority = 0;
    std::vector<uint8_t> rt_bitmap;
    rt_bitmap.resize(rt_ent_num, 0);
    //orginal code start
    //if (new_range_type) {
    //    priority = cur_range_priority;
    //    cur_range_priority -= range_group_size;
    //    range_count++;

    //    for (auto& rt_ent : relationTable) {
    //        if (rt_ent.valid && rt_ent.index_pc == new_target_pc) {
    //            rt_ent.priority = priority + 1;
    //        }
    //    }
    //} else {
    //    priority = getPriority(new_index_pc, cID) + 1;
    //    assert(priority % range_group_size > 0);
    //}
    //orginal code end
    //new update priority start
    int32_t old_range_priority = 0;
    if (new_range_type || ((new_index_pc == new_target_pc) && is_pointer_in)) {

        priority = cur_range_priority;
        old_range_priority = cur_range_priority;
        updatePriority(new_target_pc, cur_range_priority, rt_bitmap);

        if(old_range_priority == cur_range_priority){
            cur_range_priority += range_group_size;
            range_count++;
        }

        // for (auto& rt_ent : relationTable) {
        //     if (rt_ent.valid && rt_ent.index_pc == new_target_pc) {
        //         rt_ent.priority = priority + 1;
        //     }
        // }

    } else {
        priority = getPriority(new_index_pc, cID) + 1;
        updatePriority(new_target_pc, cur_range_priority, rt_bitmap);
        //assert(priority % range_group_size > 0);
    }
    //new update priority end

    int available_rt_ptr;
    bool available_rt = false;
    for (int i = 0; i < rt_ent_num; i++) {
        if (relationTable[i].valid) continue;
        available_rt = true;
        available_rt_ptr = i;
    }

    if (available_rt) {
        relationTable[available_rt_ptr].update(
            new_index_pc,
            new_target_pc,
            target_base_addr,
            shift,
            new_range_type,
            indir_range,
            cID,
            true,
            is_pointer_in,
            key_relation,
            priority
        ).validate();
        DPRINTF(LDP, "Insert RelationTable: "
            "indexPC %llx targetPC %llx target_addr %llx shift %d cID %d rangeType %d range_degree %d pointer %d priority %d on available_ptr %d\n",
            new_index_pc, new_target_pc, target_base_addr, shift, cID, new_range_type, indir_range, is_pointer_in, priority, available_rt_ptr);
    } else {
        // pointer and range RT can not be replaced
        int rt_ptr_rcd = rt_ptr;
        while (relationTable[rt_ptr].key_relation == true) {
            rt_ptr = (rt_ptr + 1) % rt_ent_num;
            if (rt_ptr == rt_ptr_rcd) {
                break; //avoid dead-loop
            }
        }

        relationTable[rt_ptr].update(
            new_index_pc,
            new_target_pc,
            target_base_addr,
            shift,
            new_range_type,
            indir_range,
            cID,
            true,
            is_pointer_in,
            key_relation,
            priority
        ).validate();
        DPRINTF(LDP, "Insert RelationTable: "
            "indexPC %llx targetPC %llx target_addr %llx shift %d cID %d rangeType %d range_degree %d pointer %d priority %d on rt_ptr %d\n",
            new_index_pc, new_target_pc, target_base_addr, shift, cID, new_range_type, indir_range, is_pointer_in, priority, rt_ptr);
        rt_ptr = (rt_ptr + 1) % rt_ent_num;
    }

}

/**
 * Insert relation into Indirect Relation Table (IRT),
 * Update priority of other entries if necessary.
 */
void
LDP::insertRT(
    iddt_ent_t& iddt_ent_match,
    tadt_ent_t& tadt_ent_match,
    int iddt_match_point, unsigned int shift, ContextID cID)
{
    Addr new_index_pc = iddt_ent_match.getPC();
    Addr new_target_pc = tadt_ent_match.getPC();
    bool is_pointer_in=false;
    // check if pattern already exist
    int rte_index = findRTE(new_index_pc, tadt_ent_match, cID);
    if (rte_index == -1) return; //find recursive RTE

    // Find or Insert corresponding IndexQueue entry.
    matchUpdate(iddt_ent_match.getPC(), tadt_ent_match.getPC(), tadt_ent_match.getContextId());


    if(tadt_ent_match.isPointer())
    {
        if(!tadt_ent_match.isEarly()){    //early version
            tadt_ent_match.update_finish();
        }
        if(new_index_pc==new_target_pc){
            iddt_ent_match.clear_early(); //early version
            iddt_ent_match.set_found(); //early version
            tadt_ent_match.clear_early(); //early version
            tadt_ent_match.set_found(); //early version
            is_pointer_in=true;
        }
    }

    // NOTE: Forced pointer type override
    if (std::find(
            pointer_type_addrs_hint.begin(),
            pointer_type_addrs_hint.end(),
            new_index_pc) != pointer_type_addrs_hint.end()) {
            is_pointer_in = true;
    }

    // calculate the target base address
    IndexData data_match = iddt_ent_match.getLast();
    for (int i = iddt_match_point; i < iddt_diff_num; i++) {
        data_match -= iddt_ent_match[i];
    }

    TargetAddr addr_match = tadt_ent_match.getLast();


    int64_t base_addr_tmp = addr_match - (data_match << shift);

    // assert(base_addr_tmp <= static_cast<uint64_t>(std::numeric_limits<int64_t>::max()));
    Addr target_base_addr = static_cast<uint64_t>(base_addr_tmp);

    if (rte_index != -2) {
        if (relationTable[rte_index].target_base_addr == target_base_addr) {
            // Need no update
            return;
        }
        relationTable[rte_index].target_base_addr = target_base_addr;
        DPRINTF(LDP, "Insert RelationTable: replace target_base_addr"
        "indexPC %llx targetPC %llx target_addr %llx\n",
        new_index_pc, new_target_pc, target_base_addr
        );
        return;
    }
    DPRINTF(LDP, "indexPC %llx targetPC %llx Matched: LastData %llx Data %llx Addr %llx Shift %d\n",
            new_index_pc, new_target_pc,iddt_ent_match.getLast(), data_match, addr_match, shift);
    /* get indexPC Range type */
    bool new_range_type;

    // Stride PC should be classified as Range
    // search for all requestor
    if(pf_helper) {
        new_range_type = pf_helper->checkStride(new_index_pc);
    } else {
        new_range_type = this->checkStride(new_index_pc);

        DPRINTF(LDP, "Check stride result: " "indexPC %llx , rangeType: %d \n",
            new_index_pc, new_range_type
        );
        // tmp: only for test
        //new_range_type = true;
    }

    // try tadt's range detection
    if (!new_range_type) {

        // check rangeTable for range type
        for (auto range_ent : rangeTable) {
            if (range_ent.target_pc != new_index_pc || range_ent.cID != cID) continue;

            new_range_type = new_range_type || range_ent.getRangeType();

            if (new_range_type == true) {
                DPRINTF(LDP, "Check stride result by getRangeType: " "indexPC %llx , rangeType: %d \n",
            new_index_pc, new_range_type);
                break;
            }
        }

    }

    //for all pointer chasing relation that have same indexPC and targetPC, set rangeType to false as default
    if (new_index_pc == new_target_pc) {
        new_range_type = false;
    }



    bool key_relation = false;
    for(auto& tadt_ent: targetAddrDeltaTable){
        if(tadt_ent.getPC() == new_index_pc && tadt_ent.isPointer()){
            key_relation = true;
            break;
        }
        if(tadt_ent.getPC() == new_target_pc && tadt_ent.isPointer()){
            key_relation = true;
            break;
        }
    }
    if(new_range_type){
        key_relation = true;
    }

    //Cannot insert self relation when link detection is disabled (origin LDP)
    if((!link_detection_enable) && new_index_pc == new_target_pc) {
        return;
    }
    insertRTEntry(
        new_index_pc,
        new_target_pc,
        target_base_addr,
        shift,
        cID,
        new_range_type,
        is_pointer_in,
        key_relation
    );
}


int32_t LDP::getPriority(Addr target_pc_in, ContextID cID_in)
{

    int32_t priority = cur_range_priority; //cur_range_priority;


    for (auto& rt_ent : relationTable) {

        if (!rt_ent.valid) continue;


        if (rt_ent.target_pc != target_pc_in) continue;


        if (cID_in != -1 && rt_ent.cID != cID_in) continue;


        priority = rt_ent.priority;
        break;
    }


    return priority;
}


void LDP::updatePriority(Addr target_pc_in, int32_t priority_in, std::vector<uint8_t>& rt_bitmap)
{

    DPRINTF(LDP, "Call updatePriority: input targetPC %llx priority %d rt_bitmap [", target_pc_in, priority_in);
    for(int i=0; i<rt_ent_num; i++){
        DPRINTF(LDP, "%d ", rt_bitmap[i]);
    }
    DPRINTF(LDP, "]\n");
    for (int i = 0; i < rt_ent_num; i++) {
        auto& rt_ent = relationTable[i];

        if (!rt_ent.valid) continue;


        if (rt_ent.index_pc != target_pc_in) continue;


        if (rt_ent.range == true || (rt_ent.target_pc == rt_ent.index_pc && rt_ent.isPointer())) {
            if (rt_bitmap[i] == 1) continue;
            cur_range_priority += range_group_size;
            range_count++;
            rt_ent.priority = cur_range_priority;
            rt_bitmap[i] = 1;
            DPRINTF(LDP, "updatePriority: indexPC %llx targetPC %llx range %d pointer %d priority %d rt_ptr %d\n", rt_ent.index_pc, rt_ent.target_pc, rt_ent.range, rt_ent.isPointer(), rt_ent.priority, i);
            break;
        }
    }

    // search for next level range group
    for (int j = 0; j < rt_ent_num; j++) {
        auto& rt_ent = relationTable[j];
        if (!rt_ent.valid) continue;
        if(rt_ent.index_pc != target_pc_in) continue;
        if(rt_bitmap[j] == 1) continue;
        if(rt_ent.range == false && rt_ent.target_pc != rt_ent.index_pc) {
            //rt_ent.priority = priority_in - (range_group_size - (rt_ent.priority % range_group_size));
            rt_ent.priority = priority_in + (rt_ent.priority % range_group_size);
            rt_bitmap[j] = 1;
            DPRINTF(LDP, "updatePriority: indexPC %llx targetPC %llx range %d pointer %d priority %d rt_ptr %d\n", rt_ent.index_pc, rt_ent.target_pc, rt_ent.range, rt_ent.isPointer(), rt_ent.priority, j);
            updatePriority(rt_ent.target_pc, cur_range_priority, rt_bitmap);
        }
   }
}


int32_t LDP::getRangeType(Addr index_pc_in, ContextID cID_in) //xymc
{

    for (auto& rt_ent : relationTable) {

        if (!rt_ent.valid) continue;


        if (rt_ent.index_pc == index_pc_in && rt_ent.cID == cID_in) {

            return rt_ent.priority;
        }
    }

    return -1;
}

bool
LDP::RangeTableEntry::updateSample(Addr addr_in)
{

    // assert(target_PC == PC_in);


    Addr addr_shifted = addr_in >> shift_times;


    if (addr_shifted == cur_tail[0] || addr_shifted == cur_tail[1])
    {
        return false;
    }


    if (addr_shifted == cur_tail[0] + 1) {
        cur_count++;

        cur_tail[1] = cur_tail[0];
        cur_tail[0] = addr_shifted;

        return false;
    }


    if (cur_count > 0) {

        int sampled_level;
        if (cur_count >= range_quant_level * range_quant_unit) {
            sampled_level = range_quant_level;
        } else {
            sampled_level = (cur_count + range_quant_unit) / range_quant_unit;
        }

        sample_count[sampled_level-1]++;
        cur_count = 0;
    }


    cur_tail[1] = cur_tail[0];
    cur_tail[0] = addr_shifted;


    return true;
}

bool LDP::RangeTableEntry::getRangeType() const {

    int sum = 0;
    [[maybe_unused]]
    int tmp_itr = 0;
    for (int sample : sample_count) {
        sum += sample;
        //printf("getRangeType: pc %lx shift_times %d  sc %d sample %d sum %d \n",
        //target_pc, shift_times ,tmp_itr, sample ,sum);
        tmp_itr++;
    }

    return (sum > range_active_th);
}

bool LDP::rangeFilter(Addr pc_in, Addr addr_in, ContextID cID_in)
{

    bool ret = true;


    for (auto& range_ent : rangeTable) {


        if (!range_ent.valid) continue;


        if (range_ent.target_pc != pc_in || range_ent.cID != cID_in) continue;


        DPRINTF(LDP, "updateSample: pc %llx shift_times %d addr %llx cur_tail %llx \n",
                    pc_in, range_ent.shift_times ,addr_in, range_ent.cur_tail);


        bool update_ret = range_ent.updateSample(addr_in);


        ret = ret && update_ret;
    }


    return ret;
}


bool LDP::offsetFilter(tadt_ent_t& tadt_ent,Addr req_addr)
{

    //--------------------------------
    // uncomment the following line to disable LINK_FILTER
    if(!offsetfilter_enable){
        return true;
    }
    //--------------------------------

    if(tadt_ent.isFinish()){

        //    return false;
        //} else {
            return true;
        //}
    }


    int64_t tmp_pointer_offset = static_cast<int64_t>(req_addr-tadt_ent.getValue());
    if(tmp_pointer_offset < offsetfilter_th && tmp_pointer_offset >= 0)
    {
        tadt_ent.update_pointer_chase(tmp_pointer_offset);
        if(tadt_ent.isEarly()){
            DPRINTF(POINTER,"offsetfilter: pc %llx addr %llx value %llx and it comes from stride causing early\n",tadt_ent.getPC(),req_addr,tadt_ent.getValue());
            return true;
        }

        DPRINTF(POINTER,"offsetfilter: pc %llx addr %llx value %llx\n",tadt_ent.getPC(),req_addr,tadt_ent.getValue());
        return false;
    }


    //    return false;
    //}


    return true;
}


void LDP::notifyL1Req(const PacketPtr &pkt)
{

    if (!pkt->isRead()) return;


    if (pkt->req == nullptr || !pkt->req->hasPC() || !pkt->req->hasVaddr()) {
        return;
    }

    Addr req_addr = pkt->req->getVaddr();


    if (req_addr > static_cast<uint64_t>(std::numeric_limits<int64_t>::max())) return;


    for (auto& tadt_ent: targetAddrDeltaTable) {

        Addr target_pc = tadt_ent.getPC();


        if (target_pc != pkt->req->getPC() || !tadt_ent.isValid()) continue;


        if (!rangeFilter(target_pc, req_addr,
                        pkt->req->hasContextId() ? pkt->req->contextId() : 0))
            continue;


        if(!offsetFilter(tadt_ent,req_addr))
            continue;


        DPRINTF(LDP, "notifyL1Req: [filter pass] PC %llx, cID %d, Addr %llx, PAddr %llx, VAddr %llx\n",
                            pkt->req->hasPC() ? pkt->req->getPC() : 0x0,
                            pkt->req->hasContextId() ? pkt->req->contextId() : 0,
                            pkt->getAddr(),
                            pkt->req->getPaddr(),
                            pkt->req->hasVaddr() ? pkt->req->getVaddr() : 0x0 );


        tadt_ent.fill(
            static_cast<TargetAddr>(pkt->req->getVaddr()),
            pkt->req->hasContextId() ? pkt->req->contextId() : 0
        );


        if (tadt_ent.isReady()) {
            DPRINTF(LDP, "try diffMatching for target PC: %llx\n", target_pc);
            diffMatching(tadt_ent);
        }
    }


    for (auto& rt_ent: relationTable) {

        if (!rt_ent.valid) continue;


        if (rt_ent.target_pc != pkt->req->getPC()) continue;


        if (rt_ent.cID!= pkt->req->hasContextId() ? pkt->req->contextId() : 0) continue;
    }




    DPRINTF(HWPrefetch, "notifyL1Req: PC %llx, Addr %llx, PAddr %llx, VAddr %llx\n",
                        pkt->req->hasPC() ? pkt->req->getPC() : 0x0,
                        pkt->getAddr(),
                        pkt->req->getPaddr(),
                        pkt->req->hasVaddr() ? pkt->req->getVaddr() : 0x0 );
}




void LDP::notifyL1Resp(const PacketPtr &pkt)
{

    if (pkt->req == nullptr || !pkt->req->hasPC()) {
        DPRINTF(HWPrefetch, "notifyL1Resp: no PC\n");
        return;
    }


    if (!pkt->validData()) {
        DPRINTF(HWPrefetch, "notifyL1Resp: PC %llx, PAddr %llx, no Data, %s\n",
                                pkt->req->getPC(), pkt->req->getPaddr(), pkt->cmdString());
        return;
    }



    const int data_stride = 8;
    const int byte_width = 8;


    if (pkt->getSize() > 8) return;
    uint8_t data[8] = {0};
    pkt->writeData(data);
    uint64_t resp_data = 0;

    for (int i_st = data_stride-1; i_st >= 0; i_st--) {
        resp_data = resp_data << byte_width;
        resp_data += static_cast<uint64_t>(data[i_st]);
    }


    // assert(resp_data <= static_cast<uint64_t>(std::numeric_limits<int64_t>::max()));//xymc
    if (resp_data > static_cast<uint64_t>(std::numeric_limits<int64_t>::max())) return;


    for (auto& tadt_ent: targetAddrDeltaTable) {

        Addr target_pc = tadt_ent.getPC();


        if (target_pc != pkt->req->getPC() || !tadt_ent.isValid()) continue;

        if(tadt_ent.isFinish())
            continue;
        IndexData new_data;
        std::memcpy(&new_data, &resp_data, sizeof(int64_t));

        if(new_data){
            tadt_ent.update_last_value(new_data);
        } else {
            DPRINTF(LDP, "Found null data: PC %llx, PAddr %llx \n", target_pc, pkt->req->getPaddr());
        }
    }


    for (auto& iddt_ent: indexDataDeltaTable) {

        if (iddt_ent.getPC() == pkt->req->getPC() && iddt_ent.isValid()) {

            IndexData new_data;
            std::memcpy(&new_data, &resp_data, sizeof(int64_t));


            if (iddt_ent.getLast() == new_data) continue;


            iddt_ent.fill(new_data, pkt->req->hasContextId() ? pkt->req->contextId() : 0);
        }
    }


    DPRINTF(LDP, "notifyL1Resp: PC %llx, PAddr %llx, VAddr %llx, Size %d, Data %llx\n",
                        pkt->req->getPC(), pkt->req->getPaddr(),
                        pkt->req->hasVaddr() ? pkt->req->getVaddr() : 0x0,
                        pkt->getSize(), resp_data);
}





void LDP::notifyFill(const PacketPtr &pkt, const uint8_t* data_ptr, bool pointer_follow, Addr pointer_follow_pc, int pointer_offset){
    constexpr unsigned maxNotifyFillDepth = 64;
    if (notifyFillDepth >= maxNotifyFillDepth) {
        DPRINTF(LDP, "notifyFill: pointer relation depth limit reached\n");
        return;
    }
    ++notifyFillDepth;
    struct DepthGuard {
        unsigned& depth;
        ~DepthGuard() { --depth; }
    } depthGuard{notifyFillDepth};


    assert(tlb != nullptr);


    if (pkt->req == nullptr || !pkt->req->hasPC()) {
        DPRINTF(HWPrefetch, "notifyFill: no PC\n");
        return;
    }


    if (!pkt->validData()) {
        DPRINTF(HWPrefetch, "notifyFill: PC %llx, PAddr %llx, no Data, %s\n",
                    pkt->req->getPC(), pkt->req->getPaddr(), pkt->cmdString());
        statsLDP.ldp_noValidData++;
        for (int i = 0; i < ldp_stats_pc.size(); i++) {
            Addr req_pc = pkt->req->getPC();
            if (req_pc == ldp_stats_pc[i]) {
                statsLDP.ldp_noValidDataPerPC[i]++;
                break;
            }
        }
        return;
    }


    const int data_stride = 8;
    const int byte_width = 8;


    Addr pc;
    Addr pkt_paddr;
    unsigned data_offset;
    if(pointer_follow){
        pc = pointer_follow_pc;
        pkt_paddr = pkt->req->getPaddr() + pointer_offset;
        int tmp_data_offset = (pkt->req->getPaddr() & (blkSize-1)) + pointer_offset;
        if(tmp_data_offset < 0 || tmp_data_offset >= blkSize) {
            DPRINTF(HWPrefetch,"notifyFill failure break: IndexPC %llx, PAddr %llx, pkt_addr %llx, pkt_offset %llx\n",pc, pkt_paddr, pkt->getAddr(), tmp_data_offset);
            return;
        }
        data_offset = pkt_paddr & (blkSize-1);
    } else {
        pc = pkt->req->getPC();
        pkt_paddr = pkt->req->getPaddr();
        data_offset = pkt->req->getPaddr() & (blkSize-1);
    }
    for (auto& rt_ent: relationTable) {

        if (!rt_ent.valid) continue;


        if (rt_ent.index_pc != pc) continue;

        if (rt_ent.is_pointer) {
            for (const auto& rt_tgt_ent: relationTable) {
                if (!rt_tgt_ent.valid) continue;
                if (rt_tgt_ent.index_pc != pc) continue;
                if (rt_tgt_ent.target_pc == pc) continue;
                int pointer_offset = rt_tgt_ent.target_base_addr-rt_ent.target_base_addr;
                for (const auto& rt_tgt_as_idx_ent: relationTable) {
                    if (!rt_tgt_as_idx_ent.valid) continue;
                    if(rt_tgt_as_idx_ent.index_pc != rt_tgt_ent.target_pc) continue;
                    notifyFill(pkt, data_ptr, true, rt_tgt_as_idx_ent.index_pc, pointer_offset);
                }
            }
        }


        unsigned range_start;
        unsigned range_end;
        if (rt_ent.range && rt_ent.is_pointer==false) {
            // continue;
            range_end = std::min(data_offset + data_stride * rt_ent.range_degree, blkSize);
            range_start = data_offset + data_stride * (rt_ent.range_degree - 1);
        } else {
            range_start = data_offset;
            range_end = data_offset + data_stride;
        }

        if (!rt_ent.isPointer() && rt_ent.target_pc == rt_ent.index_pc) {
            DPRINTF(LDP, "notifyFill: IndexPC %llx, TargetPC %llx skip since not pointer and same PC\n", rt_ent.index_pc, rt_ent.target_pc);
            continue;
        }


        for (unsigned i_of = range_start; i_of < range_end && i_of + data_stride <= blkSize; i_of += data_stride)
        {

            uint64_t resp_data = 0;
            for (int i_st = data_stride-1; i_st >= 0; i_st--) {
                resp_data = resp_data << byte_width;
                resp_data += static_cast<uint64_t>(data_ptr[i_of + i_st]);
            }


            Addr pf_addr = (resp_data << rt_ent.shift) + rt_ent.target_base_addr;
            DPRINTF(HWPrefetch,
                    "notifyFill: IndexPC %llx, TargetPC %llx, PAddr %llx, pkt_addr %llx, pkt_offset %llx, pkt_data %llx, pf_addr %llx, range_idx %d \n",
                    pc, rt_ent.target_pc, pkt_paddr, pkt->getAddr(), data_offset, resp_data, pf_addr, i_of);
            if(resp_data == 0)
                continue;
            insertIndirectPrefetch(pf_addr, rt_ent.target_pc, rt_ent.cID,
                                   rt_ent.priority, rt_ent.is_pointer);

        }


        processMissingTranslations(queueSize - pfq.size());
    }


    statsLDP.ldp_dataFill++;
}






void LDP::insertIndirectPrefetch(Addr pf_addr, Addr target_pc,
                                          ContextID cID, int32_t priority,
                                          bool is_pointer){

    Addr blk_pf_addr = blockAddress(pf_addr);



    PrefetchInfo fake_pfi(blk_pf_addr, target_pc, requestorId, cID, is_pointer);


    statsLDP.ldp_pfIdentified++;

    for (int i = 0; i < ldp_stats_pc.size(); i++) {
        if (target_pc == ldp_stats_pc[i]) {
            statsLDP.ldp_pfIdentifiedPerPfPC[i]++;
            break;
        }
    }


    if (queueFilter) {

        if (alreadyInQueue(pfq, fake_pfi, priority)) {
            // DPRINTF(HWPrefetch, "xymc\n");
            return;
        }

        if (alreadyInQueue(pfqMissingTranslation, fake_pfi, priority)) {
            return;
        }
    }

    if (detect_only) {
        DPRINTF(HWPrefetch,
                "detect_only: drop pf candidate addr:%#x from targetPC:%#x prio:%d\n",
                pf_addr, target_pc, priority);
        return;
    }


    DeferredPacket dpp(this, fake_pfi, 0, priority);


    dpp.pfInfo.setPC(target_pc);
    dpp.pfInfo.setAddr(blk_pf_addr);




    RequestPtr translation_req = std::make_shared<Request>(
        pf_addr, blkSize, Request::PREFETCH, requestorId,
        target_pc, cID);


    dpp.setTranslationRequest(translation_req);
    dpp.tc = cache->system->threads[translation_req->contextId()];



    addToQueue(pfqMissingTranslation, dpp);
}







void LDP::hitTrigger(const PacketPtr &pkt, Addr addr, const uint8_t* data_ptr, bool from_access){

    // uint8_t fill_data[blkSize];
    // std::memcpy(fill_data, data_ptr, blkSize);
    assert(pkt->req && pkt->req->hasPC() && "HitTrigger No PC");
    Addr pc = pkt->req->getPC();


    const int data_stride = 8;
    const int byte_width = 8;


    unsigned data_offset = addr & (blkSize-1);
    // data_ptr points to one cache block; do not read an 8-byte value
    // when the requested word would cross the block boundary.
    if (data_offset + data_stride > blkSize) {
        DPRINTF(LDP, "hitTrigger: data word crosses cache-block boundary\n");
        return;
    }

    for (auto& rt_ent: relationTable) {

        if (!rt_ent.valid) continue;
        if (rt_ent.index_pc != pc) continue;


        if (!from_access && rt_ent.range) continue;

        

        


        uint64_t resp_data = 0;
        for (int i_st = data_stride-1; i_st >= 0; i_st--) {
            resp_data = resp_data << byte_width;
            resp_data += static_cast<uint64_t>(data_ptr[data_offset + i_st]);
        }


        Addr pf_addr = (resp_data << rt_ent.shift) + rt_ent.target_base_addr;
        DPRINTF(HWPrefetch,
                "hitTrigger: IndexPC %llx, TargetPC %llx, Addr %llx, data_offset %llx, data %llx, pf_addr %llx\n",
                pc, rt_ent.target_pc, addr, data_offset, resp_data, pf_addr);

        insertIndirectPrefetch(pf_addr, rt_ent.target_pc, rt_ent.cID,
                               rt_ent.priority, rt_ent.is_pointer);


        processMissingTranslations(queueSize - pfq.size());
    }
}





void LDP::notify(const PacketPtr &pkt, const PrefetchInfo &pfi){

    if (pfi.isCacheMiss()) {

        DPRINTF(HWPrefetch, "notify::CacheMiss: PC %llx, Addr %llx, PAddr %llx, VAddr %llx\n",
                            pkt->req->hasPC() ? pkt->req->getPC() : 0x0,
                            pkt->getAddr(),
                            pkt->req->getPaddr(),
                            pkt->req->hasVaddr() ? pkt->req->getVaddr() : 0x0);

        notifyICSMiss(
            pkt->req->hasVaddr() ? pkt->req->getVaddr() : 0x0,
            pkt->req->hasPC() ? pkt->req->getPC() : 0x0,
            pkt->req->hasContextId () ? pkt->req->contextId() : 0
        );

    } else {

        DPRINTF(HWPrefetch, "notify::CacheHit: PC %llx, Addr %llx, PAddr %llx, VAddr %llx\n",
                            pkt->req->hasPC() ? pkt->req->getPC() : 0x0,
                            pkt->getAddr(),
                            pkt->req->getPaddr(),
                            pkt->req->hasVaddr() ? pkt->req->getVaddr() : 0x0);
    }


    assert(pkt->isRequest());





    //if (pfi.isCacheMiss) {


    // if (!pkt->req->isPrefetch()) {





        if (pkt->req->hasPC() && pkt->req->hasContextId()) {
            Addr pc = pkt->req->getPC();
            ContextID cid = pkt->req->contextId();

            int32_t access_prio = getRangeType(pc, cid);

            bool is_pointer_chasing = false;
            for (auto& rt_ent : relationTable) {

                if (!rt_ent.valid) continue;
                if (rt_ent.index_pc == rt_ent.target_pc && rt_ent.index_pc == pc && rt_ent.isPointer()) {
                    is_pointer_chasing = true;
                    break;
                }
            }


            if (access_prio % range_group_size == 0 && !is_pointer_chasing) {
            //if (access_prio % range_group_size == 0) {


                int range_level =
                    (std::numeric_limits<int32_t>::max() - access_prio) / range_group_size;


                DPRINTF(HWPrefetch, "pc %llx access_prio %d range_level : %d\n", pc, access_prio, range_level);


                int i, d;

                i = range_indirect_lookahead_start;
                d = range_indirect_lookahead_span;
                for (int ahead = i; ahead <= i + d;
                     ahead += range_indirect_lookahead_step) {

                    CacheBlk* try_cache_blk = cache->getCacheBlk(pkt->getAddr()+ahead, pkt->isSecure());
                    Addr ahead_vaddr = pkt->req->getVaddr() + ahead;
                    if (try_cache_blk != nullptr && try_cache_blk->data ) {
                        hitTrigger(pkt, ahead_vaddr, try_cache_blk->data, true);
                    } else {
                        DPRINTF(LDP, "Index pc %llx miss on Addr %llx, ahead is %d \n", pc, pkt->req->getVaddr(), ahead);
                        insertIndirectPrefetch(
                            ahead_vaddr,
                            pc, cid,
                            getPriority(pc, cid),
                            false
                        );
                        processMissingTranslations(queueSize - pfq.size());
                    }
                }
            }
            else
            {
                CacheBlk* try_cache_blk = cache->getCacheBlk(pkt->getAddr(), pkt->isSecure());

                // assert(try_cache_blk && try_cache_blk->data);

                // TODO:
                if (try_cache_blk != nullptr && try_cache_blk->data) {
                    DPRINTF(HWPrefetch, "Diaoyong: PC %llx, PAddr %llx\n",
                    pkt->req->getPC(), pkt->req->getPaddr());
                    notifyFill(pkt, try_cache_blk->data, false, 0, 0);
                }
            }
        }

    //}

    // if (pfi.isCacheMiss() && !(cache->inMissQueue(pkt->getAddr(), pkt->isSecure()))) {

        Queued::notify(pkt, pfi);
    // }
}






void LDP::callReadytoIssue(const PrefetchInfo& pfi, bool linkedFlag)
{

    Addr pc = pfi.getPC();



    if ((pc & 0xffff800000000000) == 0)
    {
        if (linkedFlag) {
            if (link_detection_enable) {
                insertIndexQueue(pc, pfi.getcID() ,true);
            }
        } else {
            insertIndexQueue(pc, pfi.getcID() ,false);
        }
    }


    if (auto_detect && !checkNewIndexEvent.scheduled())
    {


        schedule(checkNewIndexEvent, curTick() + clockPeriod() * detect_period);
    }
}


void LDP::addPfHelper(Stride* s)
{

    fatal_if(pf_helper != nullptr, "Only one PfHelper can be registered");
    pf_helper = s;
}


void LDP::calculatePrefetch(const PrefetchInfo &pfi, std::vector<AddrPriority> &addresses, const PacketPtr &pkt)
{

    if (pf_helper || detect_only) {
        std::vector<AddrPriority> fake_addresses;
        Stride::calculatePrefetch(pfi, fake_addresses, pkt);
        if (detect_only && !fake_addresses.empty()) {
            DPRINTF(HWPrefetch,
                    "detect_only: drop %zu stride candidates from PC:%#x\n",
                    fake_addresses.size(),
                    pfi.hasPC() ? pfi.getPC() : 0U);
        }
    } else {
        Stride::calculatePrefetch(pfi, addresses, pkt);
    }

    if (detect_only) {
        addresses.clear();
        return;
    }


    int32_t priority = 0;

    if (pfi.hasPC()) {
        priority = getPriority(pfi.getPC(), -1);
    }


    for (auto& addr : addresses) {
        addr.second = priority;
    }
}

} // namespace prefetch

} // namespace gem5
