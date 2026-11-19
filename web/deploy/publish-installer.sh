#!/bin/sh
# Publish a packaged installer. Run from the repository root:
#   sh web/deploy/publish-installer.sh ubuntu@main-host ~/.ssh/key.pem [mac|win]
#   mac (default): apps/desktop/dist-mac/*.dmg + latest.json            (scripts/package-mac.mjs)
#   win:           apps/desktop/dist-win/*-setup.exe + latest-win.json  (scripts/package-win.mjs)
# Copies the installer and its manifest to the main site and the mirror. When OSS_BUCKET is set in mirror.env, the mirror server
# also uploads the installer to OSS (ossutil, internal endpoint) and the manifest gets its public URL, which the download page uses.
set -eu
. web/deploy/mirror.env
main=$1; key=$2; platform=${3:-mac}
case $platform in
  mac) dist=apps/desktop/dist-mac; manifest=latest.json; file=$(basename $dist/*.dmg) ;;
  win) dist=apps/desktop/dist-win; manifest=latest-win.json; file=$(basename $dist/*-setup.exe) ;;
  *) echo "platform must be mac or win"; exit 2 ;;
esac
rsync -az --delete -e "ssh -o BatchMode=yes" "$dist/$file" "$MIRROR_SSH:/var/www/irc-web/downloads/"
json=$(cat $dist/$manifest)
if [ -n "$OSS_BUCKET" ]; then
  version=$(python3 -c "import json; print(json.load(open('$dist/$manifest'))['version'])")
  object="downloads/$version/$file"
  ssh -o BatchMode=yes "$MIRROR_SSH" "ossutil cp -f /var/www/irc-web/downloads/$file oss://$OSS_BUCKET/$object -e oss-$OSS_REGION-internal.aliyuncs.com >/dev/null && echo uploaded to OSS"
  url="https://$OSS_BUCKET.oss-$OSS_REGION.aliyuncs.com/$object"
  code=$(curl -s -o /dev/null -m 30 -r 0-0 -w '%{http_code}' "$url")
  [ "$code" = 206 ] || [ "$code" = 200 ] || { echo "OSS object is not publicly readable ($code): $url"; exit 1; }
  json=$(python3 -c "import json; d = json.load(open('$dist/$manifest')); d['url'] = '$url'; print(json.dumps(d, indent=2))")
fi
printf '%s\n' "$json" | ssh -o BatchMode=yes "$MIRROR_SSH" "cat > /var/www/irc-web/downloads/$manifest"
scp -q -i "$key" "$dist/$file" "$main:/tmp/"
printf '%s\n' "$json" | ssh -i "$key" -o BatchMode=yes "$main" "cat > /tmp/$manifest && sudo mv /tmp/$file /tmp/$manifest /opt/irc-web/static/downloads/ && sudo chmod 644 /opt/irc-web/static/downloads/*"
echo "published $file${OSS_BUCKET:+ (download button → OSS)}"
