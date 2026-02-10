# ServerGuard Interactive Shell Hook
if [ -n "$SSH_CONNECTION" ]; then
    /usr/local/bin/sg-check-access
    RET=$?
    if [ $RET -ne 0 ]; then
        kill -KILL $$
    fi
fi