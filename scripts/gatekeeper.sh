#!/bin/bash
API_URL="http://127.0.0.1:8080/check-access"

# Получаем IP и пользователя
CLIENT_IP=$(echo $SSH_CLIENT | awk '{print $1}')
USER_NAME=$(whoami)

# 1. Белый список для локальных адресов (чтобы сам сервер не заблокировал себя)
if [ -z "$CLIENT_IP" ] || [ "$CLIENT_IP" == "127.0.0.1" ] || [[ "$CLIENT_IP" == "172."* ]]; then
    exit 0
fi

# 2. Делаем запрос к API бота
# curl вернет HTTP код (200 - OK, 403 - Forbidden)
# Бот САМ отправит сообщение в Telegram, если код 403.
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${API_URL}?ip=${CLIENT_IP}&user=${USER_NAME}")

# 3. Если доступ запрещен
if [ "$HTTP_STATUS" != "200" ]; then
    # Проверяем, является ли сессия интерактивной (терминал)
    # [ -t 1 ] истина, если STDOUT открыт в терминале.
    if [ -t 1 ]; then
        # Это SSH: Можно выводить текст
        echo "==================================================="
        echo " ⛔ ACCESS DENIED "
        echo "==================================================="
        echo " IP: $CLIENT_IP"
        echo " Status: Unauthorized"
        echo " Request sent to Administrator."
        echo " Please approve in Telegram and reconnect."
        echo "==================================================="
    else
        # Это SFTP/SCP: Выводить текст НЕЛЬЗЯ (сломает протокол)
        # Мы просто молча завершаем работу с ошибкой.
        # Пользователь увидит "Connection refused" в FileZilla,
        # но получит уведомление в Telegram.
        :
    fi
    exit 1
fi

# Если доступ разрешен (200 OK)
exit 0
