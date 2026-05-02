# Auger Platform Virtual Environment Setup

## ✅ Virtual Environment Configured!

The Auger SRE Platform now uses a dedicated Python virtual environment for all dependencies.

## How It Works

### Automatic Setup
The `run.sh` script automatically:
1. Creates venv if it doesn't exist
2. Activates the venv
3. Installs/updates dependencies from `requirements.txt`
4. Runs the app using venv Python

### Benefits
✅ **Isolated dependencies** - No conflicts with system Python
✅ **Reproducible** - Same environment everywhere
✅ **Clean** - Easy to reset by deleting venv folder
✅ **All widgets work** - Shared access to dependencies

## Usage

### Start Auger Platform
```bash
cd /home/bobbygblair/repos/devtools-scripts/au-silver/astutl_python/au_sre
./run.sh
```

The script handles everything automatically!

### Run Standalone Tools (in venv context)
```bash
# Activate venv first
cd /home/bobbygblair/repos/devtools-scripts/au-silver/astutl_python/au_sre
source venv/bin/activate

# Now run any tool
python3 servicenow_auto_login.py
python3 cryptkeeper_lite.py encrypt-value
python3 -m pytest tests/
```

### OR: Run directly with venv Python
```bash
cd /home/bobbygblair/repos/devtools-scripts/au-silver/astutl_python/au_sre
venv/bin/python3 servicenow_auto_login.py
```

## Dependencies

All managed in `requirements.txt`:
```
requests>=2.31.0
python-dotenv>=1.0.0
pyyaml>=6.0.1
boto3>=1.34.0
rich>=13.7.0
click>=8.1.7
Pillow>=10.0.0
tkterm
pycryptodome>=3.20.0
selenium>=4.0.0
```

## Adding New Dependencies

### For a new widget or tool:
1. Add to `requirements.txt`
2. Restart app with `./run.sh` (auto-installs)

### Manual install:
```bash
source venv/bin/activate
pip install <package-name>
pip freeze >> requirements.txt
```

## Troubleshooting

### "No module named X"
→ Activate venv first: `source venv/bin/activate`

### Reset venv completely
```bash
rm -rf venv
./run.sh  # Recreates from scratch
```

### Check what's installed
```bash
source venv/bin/activate
pip list
```

### Verify venv is being used
```bash
source venv/bin/activate
which python3
# Should show: .../au_sre/venv/bin/python3
```

## Integration with AU Gold

Update AU Gold bash functions to use venv:

```bash
# In your AU Gold environment
PATH_TO_AU_SRE="$DIR/astutl_python/au_sre"

# Activate venv helper
au_sre_venv() {
    source "$PATH_TO_AU_SRE/venv/bin/activate"
}

# Run Auger Platform
auger() {
    pushd "$PATH_TO_AU_SRE" > /dev/null
    ./run.sh
    popd > /dev/null
}

# Run ServiceNow auto-login
servicenow_login() {
    "$PATH_TO_AU_SRE/venv/bin/python3" "$PATH_TO_AU_SRE/servicenow_auto_login.py"
}

# Run Cryptkeeper Lite
cryptkeeper_lite() {
    CRYPTKEEPER_KEY="$1" CRYPTKEEPER_VALUE="$2" \
        "$PATH_TO_AU_SRE/venv/bin/python3" "$PATH_TO_AU_SRE/cryptkeeper_lite.py" encrypt-value
}
```

## Current Status

✅ **Venv created**: `/home/bobbygblair/repos/devtools-scripts/au-silver/astutl_python/au_sre/venv`
✅ **All dependencies installed**:
   - ✅ PyCryptodome (for Cryptkeeper Lite)
   - ✅ Selenium (for ServiceNow auto-login)
   - ✅ Requests, Tkinter, Pillow, etc.
✅ **run.sh configured** to use venv automatically
✅ **All widgets have access** to dependencies

## Next Steps

1. **Restart Auger Platform** (close and run `./run.sh` again)
2. **Test Cryptkeeper Lite widget** - should work now
3. **Test ServiceNow auto-login**:
   ```bash
   source venv/bin/activate
   python3 servicenow_auto_login.py
   ```

Everything is ready to go! 🚀
