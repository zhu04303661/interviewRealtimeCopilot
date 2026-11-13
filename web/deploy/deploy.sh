#!/bin/sh
# Deploy the website to the server (idempotent). Run from the repository root:
#   sh web/deploy/deploy.sh ubuntu@host ~/.ssh/key.pem
# Leaves other Caddy sites untouched; adds /etc/caddy/sites/irc-web.conf.
set -eu
target=$1; key=$2
host=${target#*@}
ssh_() { ssh -i "$key" -o BatchMode=yes "$target" "$@"; }
rsync -az --delete -e "ssh -i $key -o BatchMode=yes" --exclude '.venv' --exclude '__pycache__' --exclude '*.sqlite3' --exclude 'tests' \
  web/server web/static "$target:/tmp/irc-web-upload/"
scp -q -i "$key" web/deploy/irc-web.service "$target:/tmp/irc-web-upload/"
ssh_ "HOST=$host sh -s" <<'REMOTE'
set -eu
sudo id ircweb >/dev/null 2>&1 || sudo useradd --system --home /var/lib/irc-web --shell /usr/sbin/nologin ircweb
sudo mkdir -p /opt/irc-web /var/lib/irc-web
sudo rsync -a --delete /tmp/irc-web-upload/server/ /opt/irc-web/server/
sudo rsync -a --delete /tmp/irc-web-upload/static/ /opt/irc-web/static/
sudo mkdir -p /opt/irc-web/static/downloads
python3 -c 'import ensurepip' 2>/dev/null || sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q python3-venv >/dev/null
[ -x /opt/irc-web/venv/bin/python ] || sudo python3 -m venv /opt/irc-web/venv
sudo /opt/irc-web/venv/bin/pip install -q --disable-pip-version-check 'aiohttp==3.14.5'
sudo chown -R ircweb:ircweb /var/lib/irc-web
if [ ! -f /etc/irc-web.env ]; then
  printf 'IRC_WEB_ORIGIN=https://%s\nIRC_WEB_DB=/var/lib/irc-web/site.sqlite3\nSTRIPE_SECRET_KEY=\nSTRIPE_WEBHOOK_SECRET=\n' "$HOST" | sudo tee /etc/irc-web.env >/dev/null
  sudo chmod 600 /etc/irc-web.env
fi
sudo cp /tmp/irc-web-upload/irc-web.service /etc/systemd/system/irc-web.service
sudo systemctl daemon-reload
sudo systemctl enable -q irc-web
sudo systemctl restart irc-web
site=/etc/caddy/sites/irc-web.conf
new=$(printf '%s {\n\tencode gzip\n\treverse_proxy 127.0.0.1:8090\n}\n' "$HOST")
if [ "$(sudo cat $site 2>/dev/null)" != "$new" ]; then
  printf '%s\n' "$new" | sudo tee $site >/dev/null
  sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null
  sudo systemctl restart caddy   # admin API is off, so Caddy cannot hot-reload
fi
rm -rf /tmp/irc-web-upload
systemctl is-active irc-web caddy
REMOTE
