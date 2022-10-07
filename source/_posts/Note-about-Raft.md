---
title: Note about Raft
date: 2022-10-07 14:30:40
tags:
---
# Note for Raft

## Why not Paxos

1. Paxos is hard to learn and understand.

2. It's hard to make a real system based on Paxos, that is, almost all real-world systems made based on Paxos turned out to have implemented an algorithm quite different from it.

## Goals for designing Raft

1. Provide a complete and practical foundation for system building

2. Safe under all conditions and available under typical os

3. Easy to understand

## Characteristics of raft

1. It's a system with a leader, while Paxos one based on peer-to-peer approach.

2. It seperates problems into serveral small ones, including leader election, log replication, safety and membership changes.

3. It simplifies the state space by reducing the number of states to consider.