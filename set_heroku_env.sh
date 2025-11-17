#!/usr/bin/env bash
APP_NAME="$1"

if [ -z "$APP_NAME" ]; then
    echo "Usage: ./set_heroku_env.sh <heroku-app-name>"
    exit 1
fi

if [ ! -f ".env" ]; then
    echo ".env file not found!"
    exit 1
fi

echo "Setting config vars for Heroku app: $APP_NAME"
echo ""

while IFS='=' read -r key value
do
    # Skip empty lines and comments
    if [[ -z "$key" || "$key" == \#* ]]; then
        continue
    fi

    # Strip possible surrounding quotes
    value="${value%\"}"
    value="${value#\"}"

    echo "→ Setting $key"
    heroku config:set "$key=$value" -a "$APP_NAME"
done < .env

echo ""
echo "Done!"
