#!/bin/bash
if [ -x /usr/local/bin/sg-gatekeeper ]; then
    /usr/local/bin/sg-gatekeeper
    RETVAL=$?
    if [ $RETVAL -ne 0 ]; then
        kill -KILL $$ 2>/dev/null
        exit 1
    fi
fi
