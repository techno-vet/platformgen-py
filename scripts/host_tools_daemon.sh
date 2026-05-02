#!/bin/bash
AUGER_DIR="$HOME/.auger"
HOST_CMD_FILE="$AUGER_DIR/.host_cmd"
HOST_RESULT_FILE="$AUGER_DIR/.host_cmd_result"
HOST_TOOLS_FILE="$AUGER_DIR/host_tools.json"
CONTAINER_NAME="auger-platform"
BROWSER_BIN=$(command -v google-chrome google-chrome-stable 2>/dev/null | head -1)

while docker inspect "$CONTAINER_NAME" &>/dev/null; do
  if [ -f "$HOST_CMD_FILE" ]; then
    CMD_JSON=$(cat "$HOST_CMD_FILE" 2>/dev/null)
    rm -f "$HOST_CMD_FILE"
    [ -z "$CMD_JSON" ] && sleep 0.5 && continue

    ACTION=$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(d.get('action',''))" "$CMD_JSON" 2>/dev/null)

    case "$ACTION" in
      open_url)
        URL=$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(d.get('args',[''])[0])" "$CMD_JSON" 2>/dev/null)
        [ -n "$URL" ] && "$BROWSER_BIN" "$URL" 2>/dev/null &
        echo '{"status":"ok"}' > "$HOST_RESULT_FILE"
        ;;
      launch_tool)
        TOOL_KEY=$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(d.get('tool',''))" "$CMD_JSON" 2>/dev/null)
        python3 -c "
import json,sys,subprocess
d=json.load(open('$HOST_TOOLS_FILE'))
t=next((t for t in d.get('tools',[]) if t['key']==sys.argv[1]),None)
if not t:
    print(json.dumps({'status':'error','message':'Tool not found'})); sys.exit()
exec_cmd=t.get('exec_cmd','')
binary=t.get('binary','')
args=t.get('args_template',[])
if exec_cmd:
    subprocess.Popen(['bash','-c',exec_cmd],start_new_session=True)
elif binary:
    subprocess.Popen([binary]+args,start_new_session=True)
else:
    print(json.dumps({'status':'error','message':'No binary or exec_cmd'})); sys.exit()
print(json.dumps({'status':'ok'}))
" "$TOOL_KEY" 2>/dev/null > "$HOST_RESULT_FILE" || echo '{"status":"error","message":"Launch failed"}' > "$HOST_RESULT_FILE"
        ;;
      find_tool)
        TOOL_NAME=$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(d.get('tool',''))" "$CMD_JSON" 2>/dev/null)
        FOUND=""
        [ -x "$TOOL_NAME" ] && FOUND="$TOOL_NAME"
        if [ -z "$FOUND" ]; then
          FOUND=$(PATH="/snap/bin:$HOME/.local/bin:$PATH" command -v "$TOOL_NAME" 2>/dev/null || echo "")
        fi
        echo "{\"status\":\"ok\",\"binary\":\"$FOUND\"}" > "$HOST_RESULT_FILE"
        ;;
      register_tool)
        python3 -c "
import json,sys
cmd=json.loads(sys.argv[1])
d=json.load(open('$HOST_TOOLS_FILE'))
key=cmd.get('key','')
d['tools']=[t for t in d.get('tools',[]) if t.get('key')!=key]
entry={'key':key,'name':cmd.get('name',key),'binary':cmd.get('binary',''),'args_template':cmd.get('args_template',[])}
if cmd.get('exec_cmd'): entry['exec_cmd']=cmd['exec_cmd']
d['tools'].append(entry)
json.dump(d,open('$HOST_TOOLS_FILE','w'),indent=2)
print(json.dumps({'status':'ok'}))
" "$CMD_JSON" 2>/dev/null > "$HOST_RESULT_FILE" || echo '{"status":"error"}' > "$HOST_RESULT_FILE"
        ;;
      list_desktop_apps)
        python3 -c "
import json, os, re, glob as gl
dirs=['$HOME/.local/share/applications','/usr/share/applications','/var/lib/snapd/desktop/applications']
apps=[]
seen=set()
for d in dirs:
    for path in gl.glob(os.path.join(d,'*.desktop')):
        try:
            name=exec_cmd=icon=''
            no_display=hidden=False
            in_entry=False
            with open(path,errors='ignore') as f:
                for line in f:
                    line=line.rstrip()
                    if line=='[Desktop Entry]': in_entry=True
                    elif line.startswith('[') and line!='[Desktop Entry]': in_entry=False
                    if not in_entry: continue
                    if line.startswith('Name=') and not name: name=line[5:]
                    elif line.startswith('Exec=') and not exec_cmd: exec_cmd=re.sub(r' ?%[fFuUdDnNickvm]','',line[5:]).strip()
                    elif line.startswith('Icon=') and not icon: icon=line[5:]
                    elif line=='NoDisplay=true': no_display=True
                    elif line=='Hidden=true': hidden=True
            if name and exec_cmd and not no_display and not hidden and name not in seen:
                seen.add(name)
                key=re.sub(r'[^a-z0-9]+','-',name.lower()).strip('-')
                apps.append({'key':key,'name':name,'exec_cmd':exec_cmd,'icon':icon})
        except: pass
apps.sort(key=lambda x:x['name'].lower())
print(json.dumps({'status':'ok','apps':apps}))
" 2>/dev/null > "$HOST_RESULT_FILE" || echo '{"status":"error","apps":[]}' > "$HOST_RESULT_FILE"
        ;;
      list_tools)
        cat "$HOST_TOOLS_FILE" > "$HOST_RESULT_FILE"
        ;;
      *)
        echo "{\"status\":\"error\",\"message\":\"Unknown: $ACTION\"}" > "$HOST_RESULT_FILE"
        ;;
    esac
  fi
  sleep 0.5
done
