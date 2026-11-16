#!/bin/sh
# Publish the packaged installer (apps/desktop/dist-mac, built by scripts/package-mac.mjs). Run from the repository root:
#   sh web/deploy/publish-installer.sh ubuntu@main-host ~/.ssh/key.pem
# Copies the DMG and latest.json to the main site and the mirror. When OSS_BUCKET is set in mirror.env, the mirror server
# also uploads the DMG to OSS (ossutil, internal endpoint) and latest.json gets its public URL, which the download page uses.
set -eu
. web/deploy/mirror.env
main=$1; key=$2
dist=apps/desktop/dist-mac
file=$(basename $dist/*.dmg)
rsync -az --delete -e "ssh -o BatchMode=yes" "$dist/$file" "$MIRROR_SSH:/var/www/irc-web/downloads/"
json=$(cat $dist/latest.json)
if [ -n "$OSS_BUCKET" ]; then
  version=$(python3 -c "import json; print(json.load(open('$dist/latest.json'))['version'])")
  object="downloads/$version/$file"
  ssh -o BatchMode=yes "$MIRROR_SSH" "ossutil cp -f /var/www/irc-web/downloads/$file oss://$OSS_BUCKET/$object -e oss-$OSS_REGION-internal.aliyuncs.com >/dev/null && echo uploaded to OSS"
  url="https://$OSS_BUCKET.oss-$OSS_REGION.aliyuncs.com/$object"
  code=$(curl -s -o /dev/null -m 30 -r 0-0 -w '%{http_code}' "$url")
  [ "$code" = 206 ] || [ "$code" = 200 ] || { echo "OSS object is not publicly readable ($code): $url"; exit 1; }
  json=$(python3 -c "import json; d = json.load(open('$dist/latest.json')); d['url'] = '$url'; print(json.dumps(d, indent=2))")
fi
printf '%s\n' "$json" | ssh -o BatchMode=yes "$MIRROR_SSH" "cat > /var/www/irc-web/downloads/latest.json"
scp -q -i "$key" "$dist/$file" "$main:/tmp/"
printf '%s\n' "$json" | ssh -i "$key" -o BatchMode=yes "$main" "cat > /tmp/latest.json && sudo mv /tmp/$file /tmp/latest.json /opt/irc-web/static/downloads/ && sudo chmod 644 /opt/irc-web/static/downloads/*"
echo "published $file${OSS_BUCKET:+ (download button → OSS)}"
