#!/bin/bash

# Проверка наличия gh cli
if ! command -v gh &> /dev/null; then
    echo "Ошибка: GitHub CLI (gh) не установлен."
    echo "Установите его: sudo apt install gh -y"
    exit 1
fi

# Проверка авторизации
if ! gh auth status &> /dev/null; then
    echo "Вы не авторизованы в GitHub CLI."
    echo "Пожалуйста, выполните: gh auth login"
    exit 1
fi

REPO_NAME="ServerGuard"
DESCRIPTION="Telegram SSH Gatekeeper & Command Logger for Ubuntu Servers"

echo "=== Инициализация Git ==="
git init
git add .
git commit -m "Initial commit: ServerGuard v1.0 Release"

echo "=== Создание репозитория на GitHub ==="
# Создаем публичный репозиторий
gh repo create "$REPO_NAME" --public --description "$DESCRIPTION" --source=. --remote=origin

echo "=== Пуш файлов ==="
git branch -M main
git push -u origin main

echo "=== Готово! ==="
echo "Ваш репозиторий доступен по ссылке:"
gh repo view --web
