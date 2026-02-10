#!/bin/bash

# 1. Perform Access Check
/usr/local/bin/sg-check-access
if [ $? -ne 0 ]; then
    exit 1
fi

# 2. Execute Original SFTP Server
# We assume standard path. If custom, installer updates this or sysadmin needs to check.
if [ -x "/usr/lib/openssh/sftp-server" ]; then
    exec /usr/lib/openssh/sftp-server "$@"
elif [ -x "/usr/libexec/openssh/sftp-server" ]; then
    exec /usr/libexec/openssh/sftp-server "$@"
else
    echo "SFTP Server binary not found."
    exit 1
fi