# Copyright (c) 2012 The Regents of The University of Michigan
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

from m5.objects import *

# Simple ALU Instructions have a latency of 1
class O3_ARM_v7a_Simple_Int(FUDesc):
    opList = [OpDesc(opClass="IntAlu", opLat=1)]
    count = 6


# Complex ALU instructions have a variable latencies
class O3_ARM_v7a_Complex_Int(FUDesc):
    opList = [
        OpDesc(opClass="IntMult", opLat=3, pipelined=True),
        OpDesc(opClass="IntDiv", opLat=12, pipelined=False),
        OpDesc(opClass="IprAccess", opLat=3, pipelined=True),
    ]
    count = 2


# Floating point and SIMD instructions
class O3_ARM_v7a_FP(FUDesc):
    opList = [
        OpDesc(opClass="SimdAdd", opLat=4),
        OpDesc(opClass="SimdAddAcc", opLat=4),
        OpDesc(opClass="SimdAlu", opLat=4),
        OpDesc(opClass="SimdCmp", opLat=4),
        OpDesc(opClass="SimdCvt", opLat=3),
        OpDesc(opClass="SimdMisc", opLat=3),
        OpDesc(opClass="SimdMult", opLat=5),
        OpDesc(opClass="SimdMultAcc", opLat=5),
        OpDesc(opClass="SimdShift", opLat=3),
        OpDesc(opClass="SimdShiftAcc", opLat=3),
        OpDesc(opClass="SimdSqrt", opLat=9),
        OpDesc(opClass="SimdFloatAdd", opLat=5),
        OpDesc(opClass="SimdFloatAlu", opLat=5),
        OpDesc(opClass="SimdFloatCmp", opLat=3),
        OpDesc(opClass="SimdFloatCvt", opLat=3),
        OpDesc(opClass="SimdFloatDiv", opLat=3),
        OpDesc(opClass="SimdFloatMisc", opLat=3),
        OpDesc(opClass="SimdFloatMult", opLat=3),
        OpDesc(opClass="SimdFloatMultAcc", opLat=5),
        OpDesc(opClass="SimdFloatSqrt", opLat=9),
        OpDesc(opClass="FloatAdd", opLat=5),
        OpDesc(opClass="FloatCmp", opLat=5),
        OpDesc(opClass="FloatCvt", opLat=5),
        OpDesc(opClass="FloatDiv", opLat=9, pipelined=False),
        OpDesc(opClass="FloatSqrt", opLat=33, pipelined=False),
        OpDesc(opClass="FloatMult", opLat=4),
        OpDesc(opClass="FloatMultAcc", opLat=5),
        OpDesc(opClass="FloatMisc", opLat=3),
    ]
    count = 2


# Load/Store Units
class O3_ARM_v7a_Load(FUDesc):
    opList = [
        OpDesc(opClass="MemRead", opLat=2),
        OpDesc(opClass="FloatMemRead", opLat=2),
    ]
    count = 2


class O3_ARM_v7a_Store(FUDesc):
    opList = [
        OpDesc(opClass="MemWrite", opLat=2),
        OpDesc(opClass="FloatMemWrite", opLat=2),
    ]
    count = 1


# Functional Units for this CPU
class O3_ARM_v7a_FUP(FUPool):
    FUList = [
        O3_ARM_v7a_Simple_Int(),
        O3_ARM_v7a_Complex_Int(),
        O3_ARM_v7a_Load(),
        O3_ARM_v7a_Store(),
        O3_ARM_v7a_FP(),
    ]


# Bi-Mode Branch Predictor
class O3_ARM_v7a_BP(BiModeBP):
    globalPredictorSize = 8192
    globalCtrBits = 2
    choicePredictorSize = 8192
    choiceCtrBits = 2
    BTBEntries = 2048
    BTBTagSize = 18
    RASSize = 16
    instShiftAmt = 2

class O3_ARM_v7a_BP_TAGE(TAGE_SC_L_64KB):
    pass

class O3_ARM_Neoverse(ArmO3CPU):
    LQEntries = 128
    SQEntries = 72
    LSQDepCheckShift = 0
    LFSTSize = 1024
    SSITSize = 1024
    decodeToFetchDelay = 1
    renameToFetchDelay = 1
    iewToFetchDelay = 1
    commitToFetchDelay = 1
    renameToDecodeDelay = 1
    iewToDecodeDelay = 1
    commitToDecodeDelay = 1
    iewToRenameDelay = 1
    commitToRenameDelay = 1
    commitToIEWDelay = 1
    fetchWidth = 8
    fetchBufferSize = 16
    fetchToDecodeDelay = 3
    decodeWidth = 6
    decodeToRenameDelay = 2
    renameWidth = 6
    renameToIEWDelay = 1
    issueToExecuteDelay = 1
    dispatchWidth = 6
    issueWidth = 6
    wbWidth = 6
    fuPool = O3_ARM_v7a_FUP()
    iewToCommitDelay = 1
    renameToROBDelay = 1
    commitWidth = 6
    squashWidth = 6
    trapLatency = 13
    backComSize = 5
    forwardComSize = 5
    numPhysIntRegs = 256
    numPhysFloatRegs = 256
    numPhysVecRegs = 128
    numIQEntries = 64
    numROBEntries = 352 

    switched_out = False
    branchPred = O3_ARM_v7a_BP_TAGE()


# Instruction Cache
class O3_ARM_v7a_ICache(Cache):
    tag_latency = 4
    data_latency = 4
    response_latency = 4
    mshrs = 8 
    tgts_per_mshr = 8
    size = "32kB"
    assoc = 8
    is_read_only = True
    # Writeback clean lines as well
    writeback_clean = False 
    tags = BaseSetAssoc()
    replacement_policy = LRURP()


# Data Cache
class O3_ARM_v7a_DCache(Cache):
    tag_latency = 5
    data_latency = 5
    response_latency = 5
    #mshrs = 6
    #tgts_per_mshr = 8
    mshrs = 8 
    tgts_per_mshr = 8
    size = "48kB"
    assoc = 12
    write_buffers = 8
    # Consider the L2 a victim cache also for clean lines
    writeback_clean = False 
    prefetch_on_access = True
    tags = BaseSetAssoc()
    replacement_policy = LRURP()


# L2 Cache
class O3_ARM_v7aL2(Cache):
    tag_latency = 10
    data_latency = 10
    response_latency = 10
    #mshrs = 16
    #tgts_per_mshr = 8
    mshrs = 32
    tgts_per_mshr = 8
    size = "512kB"
    assoc = 8
    write_buffers = 16 
    prefetch_on_access = True
    writeback_clean = True
    #clusivity = "mostly_excl"
    clusivity = "mostly_incl"
    # Simple stride prefetcher
    #prefetcher = StridePrefetcher(degree=8, latency=1)
    tags = BaseSetAssoc()
    replacement_policy = LRURP()

# L3 Cache
class O3_ARM_v7aL3(Cache):
    tag_latency = 20
    data_latency = 20
    response_latency = 20
    mshrs = 64 
    tgts_per_mshr = 12 
    size = "2MB"
    assoc = 16
    write_buffers = 8
    writeback_clean = False
    prefetch_on_access = True
    clusivity = "mostly_excl"
    # Simple stride prefetcher
    #prefetcher = StridePrefetcher(degree=8, latency=1)
    tags = BaseSetAssoc()
    replacement_policy = LRURP()