#!/bin/sh
# Deploy the mirror site (settings in web/deploy/mirror.env). Run from the repository root:
#   sh web/deploy/deploy-mirror.sh
# nginx on the mirror serves web/static and the installer from apps/desktop/dist-mac, and proxies /api and /auth to the
# main site. Adds one nginx site (irc-web-mirror); other sites on that server are not touched. The certificate is
# requested with certbot once the domain's DNS points at the server; until then the site answers on HTTP only.
set -eu
. web/deploy/mirror.env
ssh_() { ssh -o BatchMode=yes "$MIRROR_SSH" "$@"; }
ssh_ "sudo mkdir -p /var/www/irc-web/downloads && sudo chown -R \$(id -un) /var/www/irc-web"
rsync -az --delete --exclude 'downloads/' -e "ssh -o BatchMode=yes" web/static/ "$MIRROR_SSH:/var/www/irc-web/"
if ls apps/desktop/dist-mac/*.dmg >/dev/null 2>&1; then
  rsync -az --delete -e "ssh -o BatchMode=yes" apps/desktop/dist-mac/*.dmg apps/desktop/dist-mac/latest.json "$MIRROR_SSH:/var/www/irc-web/downloads/"
fi
ssh_ "DOMAIN=$MIRROR_DOMAIN MAIN=$MAIN_HOST IP=$MIRROR_IP sh -s" <<'REMOTE'
set -eu
conf=/etc/nginx/sites-available/irc-web-mirror
cert=/etc/letsencrypt/live/$DOMAIN/fullchain.pem
site() {  # $1 = "listen" lines for the content server
  cat <<NGINX
server {
$1
    server_name $DOMAIN;
    root /var/www/irc-web;
    index index.html;
    error_page 404 /404.html;
    gzip on;
    gzip_types text/css application/javascript application/json image/svg+xml text/plain application/xml;
    client_max_body_size 64m;
    location /.well-known/acme-challenge/ { root /var/www/irc-web; }
    # Accounts, subscriptions, counters: one database, on the main site.
    location ~ ^/(api|auth)/ {
        proxy_pass https://$MAIN;
        proxy_ssl_server_name on;
        proxy_set_header Host $MAIN;
        proxy_set_header X-Forwarded-For \$remote_addr;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection \$http_connection;
        proxy_read_timeout 300s;
    }
    location /downloads/ { add_header Cache-Control "no-cache"; }
    location / { try_files \$uri \$uri/index.html =404; }
}
NGINX
}
write() { printf '%s\n' "$1" | sudo tee $conf >/dev/null; sudo ln -sf $conf /etc/nginx/sites-enabled/irc-web-mirror; sudo nginx -t 2>/dev/null && sudo systemctl reload nginx; }
if ! sudo test -f "$cert"; then
  write "$(site '    listen 80;')"
  if [ "$(getent hosts "$DOMAIN" | awk '{print $1}')" = "$IP" ] || [ "$(dig +short "$DOMAIN" A 2>/dev/null | tail -1)" = "$IP" ]; then
    sudo certbot certonly --webroot -w /var/www/irc-web -d "$DOMAIN" --non-interactive --agree-tos --keep-until-expiring \
      --deploy-hook "systemctl reload nginx" >/dev/null 2>&1 || echo "certificate request failed (see /var/log/letsencrypt/letsencrypt.log)"
  else
    echo "DNS: $DOMAIN does not point at $IP yet — serving HTTP only; rerun after adding the A record."
  fi
fi
if sudo test -f "$cert"; then
  write "$(site "    listen 443 ssl;
    ssl_certificate $cert;
    ssl_certificate_key /etc/letsencrypt/live/$DOMAIN/privkey.pem;")
server {
    listen 80;
    server_name $DOMAIN;
    location /.well-known/acme-challenge/ { root /var/www/irc-web; }
    location / { return 301 https://\$host\$request_uri; }
}"
  echo "https ready"
fi
systemctl is-active nginx
REMOTE
