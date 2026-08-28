# Copyright (c) 2012-2013, 2015-2016 ARM Limited
# Copyright (c) 2020 Barkhausen Institut
# All rights reserved
#
# The license below extends only to copyright in the software and shall
# not be construed as granting a license to any other intellectual
# property including but not limited to intellectual property relating
# to a hardware implementation of the functionality of the software
# licensed hereunder.  You may use the software subject to the license
# terms below provided that you ensure that this notice is replicated
# unmodified and in its entirety in all distributions of the software,
# modified or unmodified, in source code or in binary form.
#
# Copyright (c) 2010 Advanced Micro Devices, Inc.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met: redistributions of source code must retain the above copyright
# notice, this list of conditions and the following disclaimer;
# redistributions in binary form must reproduce the above copyright
# notice, this list of conditions and the following disclaimer in the
# documentation and/or other materials provided with the distribution;
# neither the name of the copyright holders nor the names of its
# contributors may be used to endorse or promote products derived from
# this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
# THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

# Configure the M5 cache hierarchy config in one place
#

import m5
from m5.objects import *
from gem5.isas import ISA
from gem5.runtime import get_runtime_isa

from common.Caches import *
from common import ObjectList

# PC监控配置字典，键为PC地址，值为类型标签
# 字典的顺序会被保留（Python 3.7+），PC列表和类型列表会按照字典定义的顺序提取
# 如果值为空字符串或None，则不使用类型标签
#
# 注意：现在推荐通过命令行参数 --stats-pc-config 传递PC配置
# 这个默认配置仅在不传递命令行参数时使用
# 如果设置为空字典 {}，则不监控任何PC
#
# 示例配置（已注释，可通过命令行传递）：
# monitor_pc_config = {
#     0x40105c: "load",
#     0x401088: "store",
#     0x401a14: "branch",
#     0x401a2c: "load",
#     0x401a34: "",  # 不使用类型标签
#     # ... 等等
# }
monitor_pc_config = {}  # 默认不监控任何PC，需要通过 --stats-pc-config 参数传递配置


def _parse_pc_config(config_str):
    """
    解析PC配置字符串，支持JSON格式和简单格式

    参数:
        config_str: 配置字符串
            JSON格式: '{"0x40105c":"load","0x401088":"store"}'
            简单格式: '0x40105c:load,0x401088:store'

    返回:
        PC配置字典，键为PC地址（int），值为类型标签（str）
    """
    if not config_str:
        return {}

    import json

    # 尝试解析为JSON格式
    try:
        config_dict = json.loads(config_str)
        # 将字符串键转换为整数
        return {int(k, 0): v for k, v in config_dict.items()}
    except (json.JSONDecodeError, ValueError):
        pass

    # 尝试解析为简单格式 "pc:type,pc:type" 或 "pc,pc"
    try:
        config_dict = {}
        # 先去除所有空白字符（包括换行符和空格）
        config_str_clean = "".join(config_str.split())
        pairs = config_str_clean.split(",")
        for pair in pairs:
            pair = pair.strip()
            if not pair:  # 跳过空字符串
                continue
            if ":" in pair:
                pc_str, type_str = pair.split(":", 1)
                pc = int(pc_str.strip(), 0)  # 支持0x前缀
                type_label = type_str.strip()
                config_dict[pc] = type_label
            else:
                # 只有PC，没有类型
                pc = int(pair.strip(), 0)
                config_dict[pc] = ""
        return config_dict
    except ValueError:
        pass

    # 如果都解析失败，返回空字典并警告
    print(f"Warning: Failed to parse stats-pc-config: {config_str}")
    return {}


def _get_pc_config(options):
    """
    从options中获取PC配置，如果没有提供则使用默认配置

    参数:
        options: 命令行选项对象

    返回:
        PC配置字典
    """
    if hasattr(options, "stats_pc_config") and options.stats_pc_config is not None:
        # 如果传递了空字符串，表示不监控任何PC
        if options.stats_pc_config == "":
            return {}
        # 否则解析配置字符串
        return _parse_pc_config(options.stats_pc_config)
    else:
        # 如果没有提供参数，使用默认配置（通常为空字典，表示不监控）
        return monitor_pc_config


def _set_ldp_link_detection_if_supported(prefetcher, options):
    """
    仅当当前 gem5 二进制中 LDPPrefetcher 暴露 link_detection_enable 时
    才写入；旧二进制无该 Param 时跳过，使用 SimObject 编译期默认，避免 AttributeError。
    """
    if not hasattr(prefetcher, "link_detection_enable"):
        return
    prefetcher.link_detection_enable = getattr(
        options, "ldp_link_detection_enable", True
    )


def _set_ldp_range_indirect_lookahead_if_supported(prefetcher, options):
    """
    仅当当前 gem5 二进制中 LDPPrefetcher 暴露
    range_indirect_lookahead_* 时才写入；旧二进制无该 Param 时跳过，
    使用编译期默认，避免 AttributeError。
    """
    if not hasattr(prefetcher, "range_indirect_lookahead_start"):
        return
    prefetcher.range_indirect_lookahead_start = getattr(
        options, "ldp_range_indirect_lookahead_start", 64
    )
    prefetcher.range_indirect_lookahead_span = getattr(
        options, "ldp_range_indirect_lookahead_span", 1
    )
    if hasattr(prefetcher, "range_indirect_lookahead_step"):
        prefetcher.range_indirect_lookahead_step = getattr(
            options, "ldp_range_indirect_lookahead_step", 8
        )


def _configure_l1d_berti(
    berti_pf, monitor_pc_list, monitor_pc_types_list, cpu, options
):
    berti_pf.prefetch_on_access = True
    berti_pf.use_virtual_addresses = True
    berti_pf.tag_vaddr = True
    berti_pf.queue_size = 64
    berti_pf.max_prefetch_requests_with_pending_translation = 64
    berti_pf.stats_pc_list = monitor_pc_list
    if monitor_pc_types_list:
        berti_pf.stats_pc_types = monitor_pc_types_list
    berti_pf.latency = 5
    if cpu.mmu.dtb:
        print("Adding DTLB to Berti L1D prefetcher.")
        berti_pf.registerTLB(cpu.mmu.dtb)


def _configure_l1d_ldp(ldp_pf, dcache, options):
    ldp_pf.set_probe_obj(dcache, dcache, dcache)
    ldp_pf.degree = getattr(options, "stride_degree", 1)
    _set_ldp_link_detection_if_supported(ldp_pf, options)
    _set_ldp_range_indirect_lookahead_if_supported(ldp_pf, options)
    ldp_pf.offsetfilter_th = getattr(options, "ldp_offsetfilter_th", 4096)
    ldp_pf.offsetfilter_enable = getattr(
        options, "ldp_offsetfilter_enable", True
    )
    ldp_pf.stream_ahead_dist = getattr(options, "ldp_stream_ahead_dist", 64)
    ldp_pf.range_ahead_dist_level_1 = getattr(
        options, "ldp_range_ahead_dist_level_1", 0
    )
    ldp_pf.range_ahead_dist_level_2 = getattr(
        options, "ldp_range_ahead_dist_level_2", 0
    )
    ldp_pf.indir_range = getattr(options, "ldp_indir_range", 4)
    ldp_pf.replace_threshold_level_2 = getattr(
        options, "ldp_replace_th_level_2", 256
    )
    ldp_pf.auto_detect = getattr(options, "ldp_init_bench", None) is None
    ldp_pf.detect_only = getattr(options, "ldp_detect_only", False)

    if options.ldp_init_bench:
        _bench_idx = ObjectList.ldp_bench_list[options.ldp_init_bench]
        _bench_pcs = ObjectList.ldp_bench_init_pc[_bench_idx]
        ldp_pf.index_pc_init = _bench_pcs[0]
        ldp_pf.target_pc_init = _bench_pcs[1]
        ldp_pf.range_pc_init = _bench_pcs[2]
        if len(_bench_pcs) > 3:
            ldp_pf.pointer_pc_init = _bench_pcs[3]
        if len(_bench_pcs) > 4 and _bench_pcs[4]:
            ldp_pf.rt_entry_init = _bench_pcs[4]

    _iddt_diff = getattr(options, "ldp_iddt_diff_num", None)
    if _iddt_diff is not None:
        ldp_pf.iddt_diff_num = _iddt_diff
    _tadt_diff = getattr(options, "ldp_tadt_diff_num", None)
    if _tadt_diff is not None:
        ldp_pf.tadt_diff_num = _tadt_diff

    ldp_pf.prefetch_on_access = True
    ldp_pf.use_virtual_addresses = True
    ldp_pf.tag_vaddr = True
    ldp_pf.queue_size = 64
    ldp_pf.max_prefetch_requests_with_pending_translation = 64
    ldp_pf.latency = 5


def _configure_l1d_berti_ldp_composite(
    composite_pf, dcache, cpu, options, monitor_pc_list, monitor_pc_types_list
):
    berti_pf = composite_pf.prefetchers[0]
    ldp_pf = composite_pf.prefetchers[1]
    _configure_l1d_berti(
        berti_pf, monitor_pc_list, monitor_pc_types_list, cpu, options
    )
    _configure_l1d_ldp(ldp_pf, dcache, options)
    ldp_pf.stats_pc_list = monitor_pc_list
    if monitor_pc_types_list:
        ldp_pf.stats_pc_types = monitor_pc_types_list
    if cpu.mmu.dtb:
        print("Adding DTLB to LDP L1D prefetcher (composite).")
        ldp_pf.registerTLB(cpu.mmu.dtb)


def _extract_pc_lists(pc_config_dict):
    """
    从PC配置字典中提取PC列表和类型列表

    参数:
        pc_config_dict: PC地址到类型标签的字典

    返回:
        (pc_list, pc_types_list): PC地址列表和类型标签列表的元组
    """
    if not pc_config_dict:
        return [], []

    # 提取PC列表（字典的键）
    pc_list = list(pc_config_dict.keys())

    # 提取类型列表（字典的值）
    pc_types_list = list(pc_config_dict.values())

    # 如果所有类型都为空字符串或None，返回空类型列表（表示不使用类型标签）
    if all(not t for t in pc_types_list):
        return pc_list, []

    return pc_list, pc_types_list


def _get_hwp(hwp_option):
    if hwp_option == None:
        return NULL

    hwpClass = ObjectList.hwp_list.get(hwp_option)
    return hwpClass()


def _get_replply(repl_option):
    if repl_option == None:
        return NULL

    replClass = ObjectList.rp_list.get(repl_option)
    return replClass()


def _get_tag_store(tag_store_option):
    if tag_store_option == None:
        return NULL

    tagClass = ObjectList.tag_list.get(tag_store_option)
    return tagClass()


def _get_cache_opts(level, options):
    opts = {}

    size_attr = "{}_size".format(level)
    if hasattr(options, size_attr):
        opts["size"] = getattr(options, size_attr)

    assoc_attr = "{}_assoc".format(level)
    if hasattr(options, assoc_attr):
        opts["assoc"] = getattr(options, assoc_attr)

    mshr_num = "{}_mshr_num".format(level)
    if hasattr(options, mshr_num):
        opts["mshrs"] = getattr(options, mshr_num)

    prefetcher_attr = "{}_hwp_type".format(level)
    if hasattr(options, prefetcher_attr):
        opts["prefetcher"] = _get_hwp(getattr(options, prefetcher_attr))

    repl_policy_attr = "{}_repl_policy".format(level)
    if hasattr(options, repl_policy_attr):
        opts["replacement_policy"] = _get_replply(getattr(options, repl_policy_attr))

    tag_store_attr = "{}_tag_store".format(level)
    if hasattr(options, tag_store_attr):
        opts["tags"] = _get_tag_store(getattr(options, tag_store_attr))

    print(opts)

    return opts


def config_cache(options, system):
    if options.external_memory_system and (options.caches or options.l2cache):
        print("External caches and internal caches are exclusive options.\n")
        sys.exit(1)

    if options.external_memory_system:
        ExternalCache = ExternalCacheFactory(options.external_memory_system)

    if options.cpu_type == "O3_ARM_Neoverse_v2":
        try:
            # import cores.arm.O3_ARM_v7a_three_level as core
            import cores.arm.O3_ARM_v7a_paper as core

            # import cores.arm.O3_ARM_v7a_CortexA15 as core
            # import cores.arm.O3_ARM_v7a_N1 as core
        except:
            print("O3_ARM_Neoverse_v2 is unavailable. Did you compile the O3 model?")
            sys.exit(1)

        dcache_class, icache_class, l2_cache_class, walk_cache_class = (
            core.O3_ARM_v7a_DCache,
            core.O3_ARM_v7a_ICache,
            core.O3_ARM_v7aL2,
            None,
        )
    elif options.cpu_type == "HPI":
        try:
            import cores.arm.HPI as core
        except:
            print("HPI is unavailable.")
            sys.exit(1)

        dcache_class, icache_class, l2_cache_class, walk_cache_class = (
            core.HPI_DCache,
            core.HPI_ICache,
            core.HPI_L2,
            None,
        )
    else:
        dcache_class, icache_class, l2_cache_class, walk_cache_class = (
            L1_DCache,
            L1_ICache,
            L2Cache,
            None,
        )

        if get_runtime_isa() in [ISA.X86, ISA.RISCV]:
            walk_cache_class = PageTableWalkerCache

    # Set the cache line size of the system
    system.cache_line_size = options.cacheline_size

    # If elastic trace generation is enabled, make sure the memory system is
    # minimal so that compute delays do not include memory access latencies.
    # Configure the compulsory L1 caches for the O3CPU, do not configure
    # any more caches.
    if options.l2cache and options.elastic_trace_en:
        fatal("When elastic trace is enabled, do not configure L2 caches.")

    if options.l2cache:
        # Provide a clock for the L2 and the L1-to-L2 bus here as they
        # are not connected using addTwoLevelCacheHierarchy. Use the
        # same clock as the CPUs.
        system.l2 = l2_cache_class(
            clk_domain=system.cpu_clk_domain, **_get_cache_opts("l2", options)
        )

        system.tol2bus = L2XBar(clk_domain=system.cpu_clk_domain)
        system.l2.cpu_side = system.tol2bus.mem_side_ports
        system.l2.mem_side = system.membus.cpu_side_ports

    if options.memchecker:
        system.memchecker = MemChecker()

    for i in range(options.num_cpus):
        if options.caches:
            icache = icache_class(**_get_cache_opts("l1i", options))
            dcache = dcache_class(**_get_cache_opts("l1d", options))

            # If we have a walker cache specified, instantiate two
            # instances here
            if walk_cache_class:
                iwalkcache = walk_cache_class()
                dwalkcache = walk_cache_class()
            else:
                iwalkcache = None
                dwalkcache = None

            if options.memchecker:
                dcache_mon = MemCheckerMonitor(warn_only=True)
                dcache_real = dcache

                # Do not pass the memchecker into the constructor of
                # MemCheckerMonitor, as it would create a copy; we require
                # exactly one MemChecker instance.
                dcache_mon.memchecker = system.memchecker

                # Connect monitor
                dcache_mon.mem_side = dcache.cpu_side

                # Let CPU connect to monitors
                dcache = dcache_mon

            # When connecting the caches, the clock is also inherited
            # from the CPU in question
            system.cpu[i].addPrivateSplitL1Caches(
                icache, dcache, iwalkcache, dwalkcache
            )

            pc_config = _get_pc_config(options)
            monitor_pc_list, monitor_pc_types_list = _extract_pc_lists(pc_config)
            system.cpu[i].dcache.stats_pc_list = monitor_pc_list
            if monitor_pc_types_list:
                system.cpu[i].dcache.stats_pc_types = monitor_pc_types_list

            # system.cpu[i].dcache.tags = FALRU()
            # system.cpu[i].dcache.tags.min_tracked_cache_size = '16KiB'
            # system.cpu[i].dcache.replacement_policy = LRUDEPRP()
            # system.cpu[i].dcache.replacement_policy.pf_gap = getattr(options, "lru_pf_gap", 0) * 400

            if options.l1d_hwp_type == "StridePrefetcher":
                system.cpu[i].dcache.prefetcher.degree = getattr(
                    options, "stride_degree", 1
                )

            if options.l1d_hwp_type == "LDPPrefetcher":
                system.cpu[i].dcache.prefetcher.set_probe_obj(
                    system.cpu[i].dcache,
                    system.cpu[i].dcache,
                    system.cpu[i].dcache,
                )

                system.cpu[i].dcache.prefetcher.degree = getattr(
                    options, "stride_degree", 1
                )
                _set_ldp_link_detection_if_supported(
                    system.cpu[i].dcache.prefetcher, options
                )
                _set_ldp_range_indirect_lookahead_if_supported(
                    system.cpu[i].dcache.prefetcher, options
                )
                system.cpu[i].dcache.prefetcher.offsetfilter_th = getattr(
                    options, "ldp_offsetfilter_th", 4096
                )
                system.cpu[i].dcache.prefetcher.stream_ahead_dist = getattr(
                    options, "ldp_stream_ahead_dist", 64
                )
                system.cpu[i].dcache.prefetcher.range_ahead_dist_level_1 = getattr(
                    options, "ldp_range_ahead_dist_level_1", 0
                )
                system.cpu[i].dcache.prefetcher.range_ahead_dist_level_2 = getattr(
                    options, "ldp_range_ahead_dist_level_2", 0
                )
                system.cpu[i].dcache.prefetcher.indir_range = getattr(
                    options, "ldp_indir_range", 4
                )
                system.cpu[i].dcache.prefetcher.replace_threshold_level_2 = getattr(
                    options, "ldp_replace_th_level_2", 256
                )

                # system.l2.prefetcher.queue_size = 1024*1024*16
                # system.l2.prefetcher.max_prefetch_requests_with_pending_translation = 1024

                system.cpu[i].dcache.prefetcher.auto_detect = (
                    options.ldp_init_bench is None
                )
                system.cpu[i].dcache.prefetcher.detect_only = getattr(
                    options, "ldp_detect_only", False
                )

                if options.ldp_init_bench:
                    _bench_idx = ObjectList.ldp_bench_list[options.ldp_init_bench]
                    _bench_pcs = ObjectList.ldp_bench_init_pc[_bench_idx]
                    system.cpu[i].dcache.prefetcher.index_pc_init = _bench_pcs[0]
                    system.cpu[i].dcache.prefetcher.target_pc_init = _bench_pcs[1]
                    system.cpu[i].dcache.prefetcher.range_pc_init = _bench_pcs[2]
                    if len(_bench_pcs) > 3:
                        system.cpu[i].dcache.prefetcher.pointer_pc_init = _bench_pcs[3]
                    if len(_bench_pcs) > 4 and _bench_pcs[4]:
                        system.cpu[i].dcache.prefetcher.rt_entry_init = _bench_pcs[4]

                _iddt_diff = getattr(options, "ldp_iddt_diff_num", None)
                if _iddt_diff is not None:
                    system.cpu[i].dcache.prefetcher.iddt_diff_num = _iddt_diff
                _tadt_diff = getattr(options, "ldp_tadt_diff_num", None)
                if _tadt_diff is not None:
                    system.cpu[i].dcache.prefetcher.tadt_diff_num = _tadt_diff

            if options.l1d_hwp_type == "BertiPrefetcher":
                pc_config = _get_pc_config(options)
                monitor_pc_list, monitor_pc_types_list = _extract_pc_lists(
                    pc_config
                )
                _configure_l1d_berti(
                    system.cpu[i].dcache.prefetcher,
                    monitor_pc_list,
                    monitor_pc_types_list,
                    system.cpu[i],
                    options,
                )

            if options.l1d_hwp_type == "MultiPrefetcher_Berti_LDP":
                pc_config = _get_pc_config(options)
                monitor_pc_list, monitor_pc_types_list = _extract_pc_lists(
                    pc_config
                )
                _configure_l1d_berti_ldp_composite(
                    system.cpu[i].dcache.prefetcher,
                    system.cpu[i].dcache,
                    system.cpu[i],
                    options,
                    monitor_pc_list,
                    monitor_pc_types_list,
                )

            # enable VA for all prefetcher
            if options.l1d_hwp_type and options.l1d_hwp_type not in (
                "BertiPrefetcher",
                "MultiPrefetcher_Berti_LDP",
            ):
                system.cpu[i].dcache.prefetcher.queue_size = 64
                system.cpu[
                    i
                ].dcache.prefetcher.max_prefetch_requests_with_pending_translation = 64

                system.cpu[i].dcache.prefetcher.prefetch_on_access = True
                system.cpu[i].dcache.prefetcher.use_virtual_addresses = True
                system.cpu[i].dcache.prefetcher.tag_vaddr = True
                pc_config = _get_pc_config(options)
                monitor_pc_list, monitor_pc_types_list = _extract_pc_lists(pc_config)
                system.cpu[i].dcache.prefetcher.stats_pc_list = monitor_pc_list
                if monitor_pc_types_list:
                    system.cpu[
                        i
                    ].dcache.prefetcher.stats_pc_types = monitor_pc_types_list
                system.cpu[i].dcache.prefetcher.latency = 0  # xymc
                # system.cpu[i].dcache.prefetcher.latency = 5
                if system.cpu[i].mmu.dtb:
                    print("Adding DTLB to DCache prefetcher.")
                    system.cpu[i].dcache.prefetcher.registerTLB(system.cpu[i].mmu.dtb)

            if options.memchecker:
                # The mem_side ports of the caches haven't been connected yet.
                # Make sure connectAllPorts connects the right objects.
                system.cpu[i].dcache = dcache_real
                system.cpu[i].dcache_mon = dcache_mon

        elif options.external_memory_system:
            # These port names are presented to whatever 'external' system
            # gem5 is connecting to.  Its configuration will likely depend
            # on these names.  For simplicity, we would advise configuring
            # it to use this naming scheme; if this isn't possible, change
            # the names below.
            if get_runtime_isa() in [ISA.X86, ISA.ARM, ISA.RISCV]:
                system.cpu[i].addPrivateSplitL1Caches(
                    ExternalCache("cpu%d.icache" % i),
                    ExternalCache("cpu%d.dcache" % i),
                    ExternalCache("cpu%d.itb_walker_cache" % i),
                    ExternalCache("cpu%d.dtb_walker_cache" % i),
                )
            else:
                system.cpu[i].addPrivateSplitL1Caches(
                    ExternalCache("cpu%d.icache" % i),
                    ExternalCache("cpu%d.dcache" % i),
                )

        system.cpu[i].mmu.dtb.can_serialize = True

        # no need to edit for default False. Used to config here.
        # system.cpu[i].mmu.dtb.pf_translation_timing = False

        system.cpu[i].createInterruptController()
        if options.l2cache:
            assert i == 0  # only support single core
            if options.l2_hwp_type == "StridePrefetcher":
                system.l2.prefetcher.degree = getattr(options, "stride_degree", 1)

            if options.l2_hwp_type == "IrregularStreamBufferPrefetcher":
                system.l2.prefetcher.degree = getattr(options, "stride_degree", 1)

            if options.l2_hwp_type == "LDPPrefetcher":
                if options.ldp_notify == "l1":
                    system.l2.prefetcher.set_probe_obj(
                        system.cpu[i].dcache, system.cpu[i].dcache, system.l2
                    )
                if options.ldp_notify == "l2":
                    system.l2.prefetcher.set_probe_obj(
                        system.cpu[i].dcache, system.l2, system.l2
                    )

                if options.l1d_hwp_type == "StridePrefetcher":
                    print("Add L1 StridePrefetcher as L2 LDP helper.")
                    system.l2.prefetcher.set_pf_helper(system.cpu[i].dcache.prefetcher)
                else:
                    system.l2.prefetcher.degree = getattr(options, "stride_degree", 1)

                _set_ldp_link_detection_if_supported(
                    system.l2.prefetcher, options
                )
                _set_ldp_range_indirect_lookahead_if_supported(
                    system.l2.prefetcher, options
                )
                system.l2.prefetcher.offsetfilter_th = getattr(
                    options, "ldp_offsetfilter_th", 4096
                )
                system.l2.prefetcher.stream_ahead_dist = getattr(
                    options, "ldp_stream_ahead_dist", 64
                )
                # system.l2.prefetcher.range_ahead_dist = getattr(options, "ldp_range_ahead_dist", 0)
                system.l2.prefetcher.indir_range = getattr(
                    options, "ldp_indir_range", 4
                )

                system.l2.prefetcher.auto_detect = options.ldp_init_bench is None

                system.l2.prefetcher.queue_size = 1024 * 16
                system.l2.prefetcher.max_prefetch_requests_with_pending_translation = (
                    1024
                )
                # system.l2.prefetcher.queue_size = 64
                # system.l2.prefetcher.max_prefetch_requests_with_pending_translation = 64

                if options.ldp_init_bench:
                    system.l2.prefetcher.index_pc_init = ObjectList.ldp_bench_init_pc[
                        ObjectList.ldp_bench_list[options.ldp_init_bench]
                    ][0]
                    system.l2.prefetcher.target_pc_init = ObjectList.ldp_bench_init_pc[
                        ObjectList.ldp_bench_list[options.ldp_init_bench]
                    ][1]
                    system.l2.prefetcher.range_pc_init = ObjectList.ldp_bench_init_pc[
                        ObjectList.ldp_bench_list[options.ldp_init_bench]
                    ][2]

            # enable VA for all prefetcher
            if options.l2_hwp_type:
                system.l2.prefetcher.on_miss = False
                system.l2.prefetcher.use_virtual_addresses = True
                system.l2.prefetcher.tag_vaddr = True
                pc_config = _get_pc_config(options)
                monitor_pc_list, monitor_pc_types_list = _extract_pc_lists(pc_config)
                system.l2.prefetcher.stats_pc_list = monitor_pc_list
                if monitor_pc_types_list:
                    system.l2.prefetcher.stats_pc_types = monitor_pc_types_list
                system.l2.prefetcher.latency = 15
                # system.l2.prefetcher.latency = 17
                if system.cpu[i].mmu.dtb:
                    print("Adding DTLB to L2 prefetcher.")
                    system.l2.prefetcher.registerTLB(system.cpu[i].mmu.dtb)

            pc_config = _get_pc_config(options)
            monitor_pc_list, monitor_pc_types_list = _extract_pc_lists(pc_config)
            system.l2.stats_pc_list = monitor_pc_list
            if monitor_pc_types_list:
                system.l2.stats_pc_types = monitor_pc_types_list

            system.cpu[i].connectAllPorts(
                system.tol2bus.cpu_side_ports,
                system.membus.cpu_side_ports,
                system.membus.mem_side_ports,
            )
        elif options.external_memory_system:
            system.cpu[i].connectUncachedPorts(
                system.membus.cpu_side_ports, system.membus.mem_side_ports
            )
        else:
            system.cpu[i].connectBus(system.membus)

    return system


def config_three_level_cache(options, system):
    if options.external_memory_system and (options.caches or options.l2cache):
        print("External caches and internal caches are exclusive options.\n")
        sys.exit(1)

    if options.external_memory_system:
        ExternalCache = ExternalCacheFactory(options.external_memory_system)

    if options.cpu_type == "O3_ARM_Neoverse_v2":
        try:
            #import cores.arm.O3_ARM_v7a_Xeon6_Like as core
            import cores.arm.O3_ARM_v7a_z_Neoverse_v2 as core
        except:
            print("O3_ARM_Neoverse_v2 is unavailable. Did you compile the O3 model?")
            sys.exit(1)

        (
            dcache_class,
            icache_class,
            l2_cache_class,
            l3_cache_class,
            walk_cache_class,
        ) = (
            core.O3_ARM_v7a_DCache,
            core.O3_ARM_v7a_ICache,
            core.O3_ARM_v7aL2,
            core.O3_ARM_v7aL3,
            None,
        )
    elif options.cpu_type == "O3_ARM_Neoverse":
        try:
            import cores.arm.O3_ARM_Neoverse as core
        except:
            print("O3_ARM_Neoverse is unavailable. Did you compile the O3 model?")
            sys.exit(1)

        (
            dcache_class,
            icache_class,
            l2_cache_class,
            l3_cache_class,
            walk_cache_class,
        ) = (
            core.O3_ARM_v7a_DCache,
            core.O3_ARM_v7a_ICache,
            core.O3_ARM_v7aL2,
            core.O3_ARM_v7aL3,
            None,
        )
    else:
        (
            dcache_class,
            icache_class,
            l2_cache_class,
            l3_cache_class,
            walk_cache_class,
        ) = (
            L1_DCache,
            L1_ICache,
            L2Cache,
            L3Cache,
            None,
        )

        if get_runtime_isa() in [ISA.X86, ISA.RISCV]:
            walk_cache_class = PageTableWalkerCache

    # Set the cache line size of the system
    system.cache_line_size = options.cacheline_size

    # If elastic trace generation is enabled, make sure the memory system is
    # minimal so that compute delays do not include memory access latencies.
    # Configure the compulsory L1 caches for the O3CPU, do not configure
    # any more caches.
    if options.l2cache and options.elastic_trace_en:
        fatal("When elastic trace is enabled, do not configure L2 caches.")

    if options.l3cache and options.elastic_trace_en:
        fatal("When elastic trace is enabled, do not configure L3 caches.")

    if options.l3cache:
        # Provide a clock for the L2 and the L1-to-L2 bus here as they
        # are not connected using addTwoLevelCacheHierarchy. Use the
        # same clock as the CPUs.
        system.l3 = l3_cache_class(
            clk_domain=system.cpu_clk_domain, **_get_cache_opts("l3", options)
        )

        system.tol3bus = L3XBar(clk_domain=system.cpu_clk_domain)
        system.l3.cpu_side = system.tol3bus.mem_side_ports
        system.l3.mem_side = system.membus.cpu_side_ports

    if options.memchecker:
        system.memchecker = MemChecker()

    for i in range(options.num_cpus):
        if options.caches:
            icache = icache_class(**_get_cache_opts("l1i", options))
            dcache = dcache_class(**_get_cache_opts("l1d", options))

            # If we have a walker cache specified, instantiate two
            # instances here
            if walk_cache_class:
                iwalkcache = walk_cache_class()
                dwalkcache = walk_cache_class()
            else:
                iwalkcache = None
                dwalkcache = None

            if options.memchecker:
                dcache_mon = MemCheckerMonitor(warn_only=True)
                dcache_real = dcache

                # Do not pass the memchecker into the constructor of
                # MemCheckerMonitor, as it would create a copy; we require
                # exactly one MemChecker instance.
                dcache_mon.memchecker = system.memchecker

                # Connect monitor
                dcache_mon.mem_side = dcache.cpu_side

                # Let CPU connect to monitors
                dcache = dcache_mon

            # When connecting the caches, the clock is also inherited
            # from the CPU in question
            system.cpu[i].addPrivateSplitL1Caches(
                icache, dcache, iwalkcache, dwalkcache
            )

            pc_config = _get_pc_config(options)
            monitor_pc_list, monitor_pc_types_list = _extract_pc_lists(pc_config)
            system.cpu[i].dcache.stats_pc_list = monitor_pc_list
            if monitor_pc_types_list:
                system.cpu[i].dcache.stats_pc_types = monitor_pc_types_list
            if options.l1d_hwp_type == "StridePrefetcher":
                system.cpu[i].dcache.prefetcher.degree = getattr(
                    options, "stride_degree", 4
                )
            if options.l1d_hwp_type == "LDPPrefetcher":
                system.cpu[i].dcache.prefetcher.set_probe_obj(
                    system.cpu[i].dcache,
                    system.cpu[i].dcache,
                    system.cpu[i].dcache,
                )

                system.cpu[i].dcache.prefetcher.degree = getattr(
                    options, "stride_degree", 1
                )
                _set_ldp_link_detection_if_supported(
                    system.cpu[i].dcache.prefetcher, options
                )
                _set_ldp_range_indirect_lookahead_if_supported(
                    system.cpu[i].dcache.prefetcher, options
                )
                system.cpu[i].dcache.prefetcher.offsetfilter_th = getattr(
                    options, "ldp_offsetfilter_th", 4096
                )
                system.cpu[i].dcache.prefetcher.offsetfilter_enable = getattr(
                    options, "ldp_offsetfilter_enable", True
                )
                system.cpu[i].dcache.prefetcher.stream_ahead_dist = getattr(
                    options, "ldp_stream_ahead_dist", 64
                )
                system.cpu[i].dcache.prefetcher.range_ahead_dist_level_1 = getattr(
                    options, "ldp_range_ahead_dist_level_1", 0
                )
                system.cpu[i].dcache.prefetcher.range_ahead_dist_level_2 = getattr(
                    options, "ldp_range_ahead_dist_level_2", 0
                )
                system.cpu[i].dcache.prefetcher.indir_range = getattr(
                    options, "ldp_indir_range", 4
                )
                system.cpu[i].dcache.prefetcher.replace_threshold_level_2 = getattr(
                    options, "ldp_replace_th_level_2", 256
                )

                # system.l2.prefetcher.queue_size = 1024*1024*16
                # system.l2.prefetcher.max_prefetch_requests_with_pending_translation = 1024

                system.cpu[i].dcache.prefetcher.auto_detect = (
                    getattr(options, "ldp_init_bench", None) is None
                )
                system.cpu[i].dcache.prefetcher.detect_only = getattr(
                    options, "ldp_detect_only", False
                )

                if options.ldp_init_bench:
                    _bench_idx3 = ObjectList.ldp_bench_list[options.ldp_init_bench]
                    _bench_pcs3 = ObjectList.ldp_bench_init_pc[_bench_idx3]
                    system.cpu[i].dcache.prefetcher.index_pc_init = _bench_pcs3[0]
                    system.cpu[i].dcache.prefetcher.target_pc_init = _bench_pcs3[1]
                    system.cpu[i].dcache.prefetcher.range_pc_init = _bench_pcs3[2]
                    if len(_bench_pcs3) > 3:
                        system.cpu[i].dcache.prefetcher.pointer_pc_init = _bench_pcs3[3]
                    if len(_bench_pcs3) > 4 and _bench_pcs3[4]:
                        system.cpu[i].dcache.prefetcher.rt_entry_init = _bench_pcs3[4]

                _iddt_diff3 = getattr(options, "ldp_iddt_diff_num", None)
                if _iddt_diff3 is not None:
                    system.cpu[i].dcache.prefetcher.iddt_diff_num = _iddt_diff3
                _tadt_diff3 = getattr(options, "ldp_tadt_diff_num", None)
                if _tadt_diff3 is not None:
                    system.cpu[i].dcache.prefetcher.tadt_diff_num = _tadt_diff3

            if options.l1d_hwp_type == "BertiPrefetcher":
                pc_config = _get_pc_config(options)
                monitor_pc_list, monitor_pc_types_list = _extract_pc_lists(
                    pc_config
                )
                _configure_l1d_berti(
                    system.cpu[i].dcache.prefetcher,
                    monitor_pc_list,
                    monitor_pc_types_list,
                    system.cpu[i],
                    options,
                )

            if options.l1d_hwp_type == "MultiPrefetcher_Berti_LDP":
                pc_config = _get_pc_config(options)
                monitor_pc_list, monitor_pc_types_list = _extract_pc_lists(
                    pc_config
                )
                _configure_l1d_berti_ldp_composite(
                    system.cpu[i].dcache.prefetcher,
                    system.cpu[i].dcache,
                    system.cpu[i],
                    options,
                    monitor_pc_list,
                    monitor_pc_types_list,
                )

            # enable VA for all prefetcher
            if options.l1d_hwp_type and options.l1d_hwp_type not in (
                "BertiPrefetcher",
                "MultiPrefetcher_Berti_LDP",
            ):
                system.cpu[i].dcache.prefetcher.prefetch_on_access = True
                system.cpu[i].dcache.prefetcher.use_virtual_addresses = True
                system.cpu[i].dcache.prefetcher.tag_vaddr = True
                pc_config = _get_pc_config(options)
                monitor_pc_list, monitor_pc_types_list = _extract_pc_lists(pc_config)
                system.cpu[i].dcache.prefetcher.stats_pc_list = monitor_pc_list
                if monitor_pc_types_list:
                    system.cpu[
                        i
                    ].dcache.prefetcher.stats_pc_types = monitor_pc_types_list
                # system.cpu[i].dcache.prefetcher.latency = 3
                system.cpu[i].dcache.prefetcher.latency = 5
                if system.cpu[i].mmu.dtb:
                    print("Adding DTLB to DCache prefetcher.")
                    system.cpu[i].dcache.prefetcher.registerTLB(system.cpu[i].mmu.dtb)
            if options.memchecker:
                # The mem_side ports of the caches haven't been connected yet.
                # Make sure connectAllPorts connects the right objects.
                system.cpu[i].dcache = dcache_real
                system.cpu[i].dcache_mon = dcache_mon
        # The default LDP profile uses 64-entry L1 ITLB/DTLB and a 1280-entry
        # shared L2 TLB. The gem5_comb profile used a larger DTLB.
        if options.cpu_type == "O3_ARM_Neoverse":
            system.cpu[i].mmu.dtb.size = 262144
        system.cpu[i].mmu.dtb.can_serialize = True

        # no need to edit for default False. Used to config here.
        # system.cpu[i].mmu.dtb.pf_translation_timing = False

        system.cpu[i].createInterruptController()

        if options.l2cache and options.l3cache:
            system.cpu[i].l2 = l2_cache_class(
                clk_domain=system.cpu_clk_domain,
                **_get_cache_opts("l2", options),
            )

            system.cpu[i].l2.prefetcher.queue_size = 64
            system.cpu[
                i
            ].l2.prefetcher.max_prefetch_requests_with_pending_translation = 64

            if options.l2_hwp_type == "StridePrefetcher":
                system.cpu[i].l2.prefetcher.degree = getattr(
                    options, "stride_degree", 4
                )

            if options.l2_hwp_type == "IrregularStreamBufferPrefetcher":
                system.cpu[i].l2.prefetcher.degree = getattr(
                    options, "stride_degree", 4
                )

            if options.l2_hwp_type == "LDPPrefetcher":
                system.cpu[i].l2.prefetcher.set_probe_obj(
                    system.cpu[i].dcache, system.cpu[i].l2
                )
                system.cpu[i].l2.prefetcher.degree = getattr(
                    options, "stride_degree", 4
                )
                _set_ldp_link_detection_if_supported(
                    system.cpu[i].l2.prefetcher, options
                )
                _set_ldp_range_indirect_lookahead_if_supported(
                    system.cpu[i].l2.prefetcher, options
                )

                system.cpu[i].l2.prefetcher.stream_ahead_dist = getattr(
                    options, "ldp_stream_ahead_dist", 64
                )
                system.cpu[i].l2.prefetcher.indir_range = getattr(
                    options, "ldp_indir_range", 4
                )
                # system.l2.prefetcher.queue_size = 1024*1024*16
                # system.l2.prefetcher.max_prefetch_requests_with_pending_translation = 1024

                if options.ldp_init_bench:
                    system.cpu[
                        i
                    ].l2.prefetcher.index_pc_init = ObjectList.ldp_bench_init_pc[
                        ObjectList.ldp_bench_list[options.ldp_init_bench]
                    ][0]
                    system.cpu[
                        i
                    ].l2.prefetcher.target_pc_init = ObjectList.ldp_bench_init_pc[
                        ObjectList.ldp_bench_list[options.ldp_init_bench]
                    ][1]
                    system.cpu[
                        i
                    ].l2.prefetcher.range_pc_init = ObjectList.ldp_bench_init_pc[
                        ObjectList.ldp_bench_list[options.ldp_init_bench]
                    ][2]

            # enable VA for all prefetcher
            if options.l2_hwp_type:
                system.cpu[i].l2.prefetcher.use_virtual_addresses = True
                if system.cpu[i].mmu.dtb:
                    print("Adding DTLB to L2 prefetcher.")
                    system.cpu[i].l2.prefetcher.registerTLB(system.cpu[i].mmu.dtb)

            system.cpu[i].tol2bus = L2XBar(clk_domain=system.cpu_clk_domain)
            system.cpu[i].l2.cpu_side = system.cpu[i].tol2bus.mem_side_ports
            system.cpu[i].l2.mem_side = system.tol3bus.cpu_side_ports

            system.cpu[i].connectAllPorts(
                system.cpu[i].tol2bus.cpu_side_ports,
                system.membus.cpu_side_ports,
                system.membus.mem_side_ports,
            )

        else:
            system.cpu[i].connectBus(system.membus)

    return system


def config_three_level_cache_org(options, system):
    if options.external_memory_system and (options.caches or options.l2cache):
        print("External caches and internal caches are exclusive options.\n")
        sys.exit(1)

    if options.external_memory_system:
        ExternalCache = ExternalCacheFactory(options.external_memory_system)

    if options.cpu_type == "O3_ARM_Neoverse_v2":
        try:
            import cores.arm.O3_ARM_v7a_three_level as core
        except:
            print("O3_ARM_Neoverse_v2 is unavailable. Did you compile the O3 model?")
            sys.exit(1)

        (
            dcache_class,
            icache_class,
            l2_cache_class,
            l3_cache_class,
            walk_cache_class,
        ) = (
            core.O3_ARM_v7a_DCache,
            core.O3_ARM_v7a_ICache,
            core.O3_ARM_v7aL2,
            core.O3_ARM_v7aL3,
            None,
        )
    else:
        (
            dcache_class,
            icache_class,
            l2_cache_class,
            l3_cache_class,
            walk_cache_class,
        ) = (
            L1_DCache,
            L1_ICache,
            L2Cache,
            L3Cache,
            None,
        )

        if get_runtime_isa() in [ISA.X86, ISA.RISCV]:
            walk_cache_class = PageTableWalkerCache

    # Set the cache line size of the system
    system.cache_line_size = options.cacheline_size

    # If elastic trace generation is enabled, make sure the memory system is
    # minimal so that compute delays do not include memory access latencies.
    # Configure the compulsory L1 caches for the O3CPU, do not configure
    # any more caches.
    if options.l2cache and options.elastic_trace_en:
        fatal("When elastic trace is enabled, do not configure L2 caches.")

    if options.l3cache and options.elastic_trace_en:
        fatal("When elastic trace is enabled, do not configure L3 caches.")

    if options.l3cache:
        # Provide a clock for the L2 and the L1-to-L2 bus here as they
        # are not connected using addTwoLevelCacheHierarchy. Use the
        # same clock as the CPUs.
        system.l3 = l3_cache_class(
            clk_domain=system.cpu_clk_domain, **_get_cache_opts("l3", options)
        )

        system.tol3bus = L3XBar(clk_domain=system.cpu_clk_domain)
        system.l3.cpu_side = system.tol3bus.mem_side_ports
        system.l3.mem_side = system.membus.cpu_side_ports

    if options.memchecker:
        system.memchecker = MemChecker()

    for i in range(options.num_cpus):
        if options.caches:
            icache = icache_class(**_get_cache_opts("l1i", options))
            dcache = dcache_class(**_get_cache_opts("l1d", options))

            # If we have a walker cache specified, instantiate two
            # instances here
            if walk_cache_class:
                iwalkcache = walk_cache_class()
                dwalkcache = walk_cache_class()
            else:
                iwalkcache = None
                dwalkcache = None
            system.cpu[i].addPrivateSplitL1Caches(
                icache, dcache, iwalkcache, dwalkcache
            )

        system.cpu[i].mmu.dtb.can_serialize = True

        # no need to edit for default False. Used to config here.
        # system.cpu[i].mmu.dtb.pf_translation_timing = False

        system.cpu[i].createInterruptController()

        if options.l2cache and options.l3cache:
            system.cpu[i].l2 = l2_cache_class(
                clk_domain=system.cpu_clk_domain,
                **_get_cache_opts("l2", options),
            )

            if options.l2_hwp_type == "StridePrefetcher":
                system.cpu[i].l2.prefetcher.degree = getattr(
                    options, "stride_degree", 1
                )

            if options.l2_hwp_type == "IrregularStreamBufferPrefetcher":
                system.cpu[i].l2.prefetcher.degree = getattr(
                    options, "stride_degree", 1
                )

            if options.l2_hwp_type == "LDPPrefetcher":
                system.cpu[i].l2.prefetcher.set_probe_obj(
                    system.cpu[i].dcache, system.cpu[i].l2
                )
                system.cpu[i].l2.prefetcher.degree = getattr(
                    options, "stride_degree", 1
                )
                _set_ldp_link_detection_if_supported(
                    system.cpu[i].l2.prefetcher, options
                )
                _set_ldp_range_indirect_lookahead_if_supported(
                    system.cpu[i].l2.prefetcher, options
                )

                system.cpu[i].l2.prefetcher.offsetfilter_th = getattr(
                    options, "ldp_offsetfilter_th", 4096
                )
                system.cpu[i].l2.prefetcher.stream_ahead_dist = getattr(
                    options, "ldp_stream_ahead_dist", 64
                )
                system.cpu[i].l2.prefetcher.indir_range = getattr(
                    options, "ldp_indir_range", 4
                )
                # system.l2.prefetcher.queue_size = 1024*1024*16
                # system.l2.prefetcher.max_prefetch_requests_with_pending_translation = 1024

                if options.ldp_init_bench:
                    system.cpu[
                        i
                    ].l2.prefetcher.index_pc_init = ObjectList.ldp_bench_init_pc[
                        ObjectList.ldp_bench_list[options.ldp_init_bench]
                    ][0]
                    system.cpu[
                        i
                    ].l2.prefetcher.target_pc_init = ObjectList.ldp_bench_init_pc[
                        ObjectList.ldp_bench_list[options.ldp_init_bench]
                    ][1]
                    system.cpu[
                        i
                    ].l2.prefetcher.range_pc_init = ObjectList.ldp_bench_init_pc[
                        ObjectList.ldp_bench_list[options.ldp_init_bench]
                    ][2]

            # enable VA for all prefetcher
            if options.l2_hwp_type:
                system.cpu[i].l2.prefetcher.use_virtual_addresses = True
                if system.cpu[i].mmu.dtb:
                    print("Adding DTLB to L2 prefetcher.")
                    system.cpu[i].l2.prefetcher.registerTLB(system.cpu[i].mmu.dtb)

            system.cpu[i].tol2bus = L2XBar(clk_domain=system.cpu_clk_domain)
            system.cpu[i].l2.cpu_side = system.cpu[i].tol2bus.mem_side_ports
            system.cpu[i].l2.mem_side = system.tol3bus.cpu_side_ports

            system.cpu[i].connectAllPorts(
                system.cpu[i].tol2bus.cpu_side_ports,
                system.membus.cpu_side_ports,
                system.membus.mem_side_ports,
            )

        else:
            system.cpu[i].connectBus(system.membus)

    return system


# ExternalSlave provides a "port", but when that port connects to a cache,
# the connecting CPU SimObject wants to refer to its "cpu_side".
# The 'ExternalCache' class provides this adaptation by rewriting the name,
# eliminating distracting changes elsewhere in the config code.
class ExternalCache(ExternalSlave):
    def __getattr__(cls, attr):
        if attr == "cpu_side":
            attr = "port"
        return super(ExternalSlave, cls).__getattr__(attr)

    def __setattr__(cls, attr, value):
        if attr == "cpu_side":
            attr = "port"
        return super(ExternalSlave, cls).__setattr__(attr, value)


def ExternalCacheFactory(port_type):
    def make(name):
        return ExternalCache(
            port_data=name, port_type=port_type, addr_ranges=[AllMemory]
        )

    return make
