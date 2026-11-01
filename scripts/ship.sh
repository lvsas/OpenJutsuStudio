#!/usr/bin/env bash
# Publie main et prépare la mise à jour de l'instance du jury.
#
# Une seule règle : rien ne part vers le jury sans une CI verte sur le commit
# publié. Le déploiement lui-même reste une commande sudo, exécutée par l'humain.
set -euo pipefail

REPO="lvsas/OpenJutsuStudio"
JURY="${SHIP_JURY_HOST:-ojs-jury}"
SSH_OPTS=(-o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null)
BRANCH="main"

step() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

step "1/6 arbre de travail"
[ -z "$(git status --porcelain)" ] || { printf 'Arbre sale : commit ou stash avant de publier.\n' >&2; exit 1; }
[ "$(git rev-parse --abbrev-ref HEAD)" = "$BRANCH" ] || { printf 'Pas sur %s.\n' "$BRANCH" >&2; exit 1; }

step "2/6 suite de tests"
PYTHONPATH=src:tests .venv/bin/python -m unittest discover -s tests -q

step "3/6 publication"
git push -q origin "$BRANCH"
SHA=$(git rev-parse HEAD)
printf 'commit %s\n' "$(git rev-parse --short HEAD)"

step "4/6 CI GitHub sur ce commit"
conclusion="none"
for _ in $(seq 1 40); do
  sleep 20
  read -r status conclusion <<<"$(curl -s -m 20 \
    "https://api.github.com/repos/$REPO/actions/runs?head_sha=$SHA&per_page=1" \
    | python3 -c 'import json,sys
runs=json.load(sys.stdin).get("workflow_runs") or []
print((runs[0]["status"], runs[0]["conclusion"]) if runs else ("none", "none"))')"
  printf '   %s / %s\n' "$status" "$conclusion"
  [ "$status" = "completed" ] && break
done
if [ "$conclusion" != "success" ]; then
  printf 'CI non verte (%s) : aucune mise à jour du jury.\n' "$conclusion" >&2
  exit 1
fi

step "5/6 préparation côté jury"
ssh "${SSH_OPTS[@]}" "$JURY" "cd ~/openjutsu && git fetch -q origin && git checkout -q $SHA" 
ssh "${SSH_OPTS[@]}" "$JURY" 'cat > ~/apply-update.sh' <<'REMOTE'
#!/usr/bin/env bash
set -euo pipefail
rsync -a --delete --exclude .git --exclude .venv --exclude work /home/studio/openjutsu/ /srv/ojs/app/
chown -R ojs:ojs /srv/ojs/app
systemctl restart ojs-app.service
sleep 3
systemctl is-active ojs-app.service
curl -s -o /dev/null -w "health=%{http_code}\n" http://127.0.0.1:8000/health
curl -s -m 20 http://127.0.0.1:8000/api/readiness | head -c 200
echo
REMOTE
ssh "${SSH_OPTS[@]}" "$JURY" 'chmod +x ~/apply-update.sh'

step "6/6 il ne reste qu'à lancer"
printf '\n  ssh %s "sudo bash ~/apply-update.sh"\n\n' "$JURY"
