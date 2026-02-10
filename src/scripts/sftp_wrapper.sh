#!/bin/bash
# ServerGuard SFTP Wrapper
/usr/local/bin/sg-check-access
if [ $? -ne 0 ]; then
    exit 1
fi

if [ -x "/usr/lib/openssh/sftp-server" ]; then
    exec /usr/lib/openssh/sftp-server "$@"
elif [ -x "/usr/libexec/openssh/sftp-server" ]; then
    exec /usr/libexec/openssh/sftp-server "$@"
else
    echo "SFTP Server binary not found."
    exit 1
fi