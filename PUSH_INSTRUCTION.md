# Push instruction

```bash
cd ~/Downloads

rm -rf ~/Desktop/joot_clean_push
mkdir -p ~/Desktop/joot_clean_push

unzip -o joot_clean_production_v7_joot8_ui_clean.zip -d ~/Desktop/joot_clean_push
cd ~/Desktop/joot_clean_push

rm -rf .git .gitmodules repo

ls -la Dockerfile
ls -la app/main.py

find . -name .git -o -name .gitmodules
find . -maxdepth 2 -name repo

git init
git branch -M main
git remote add origin https://github.com/dud0k3/joot_app.git

git add .
git commit -m "JOOT v7 clean 8-config subscription UI"
git push -f origin main
```

После push в Dockhost нажать `Redeploy / Rebuild`, не просто Restart.

Проверка:

```text
https://0fd6-sk2c-fsin.gw-1a.dockhost.net/api/version
```

Ожидаемая версия:

```text
joot-clean-production-2026-06-29-v7-joot8-ui-clean
```
