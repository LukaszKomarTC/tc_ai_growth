#!/bin/bash
# WP-U4d — the permission predicate, extracted (PR #79, reduced scope).
#
# This file exists on its own because it is the ONE part of the privileged-helper work that is
# genuinely finished and proven. The helper and installer it was written for were withdrawn from
# PR #79: their root execution chain was not safe (root ran Python and installed scripts from a
# service-user-writable checkout), and shipping a proven predicate inside an unproven boundary
# would have let the explanation outrun the implementation again.
#
# Source this from privileged shell programs. It defines one function and nothing else.
#
# ---------------------------------------------------------------------------------------------
# Refuse any path carrying a group- or other-write bit.
#
# Implemented as a NUMERIC MASK, not a glob. The first version of this guard used
# "root:root "[0-7][0-57][0-57], and a shell character range cannot express "no write bit":
# [0-57] is the set {0,1,2,3,4,5,7}, so it accepted 2, 3 and 7 — every one of them writable.
# 0777 passed a check whose own error message said "not group/other writable" (PR #79 round 3).
#
# Fails closed: an unreadable or non-octal mode is treated as unsafe rather than assumed fine.
# ---------------------------------------------------------------------------------------------
mode_has_write_bits() {
    # $1 is an octal mode from `stat -c %a`, 3 or 4 digits. 8#22 is g+w | o+w.
    local mode="$1"
    [ -n "$mode" ] || return 0                   # unreadable mode => unsafe
    case "$mode" in *[!0-7]*) return 0 ;; esac    # not octal => unsafe
    (( 8#$mode & 8#22 ))
}
