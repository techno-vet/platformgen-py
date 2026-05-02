# Cryptkeeper Widget

The Cryptkeeper widget provides a secure interface for encrypting and decrypting configuration values using Jasypt encryption.

## Features

### 🔐 Encryption/Decryption
- **Auto-detect mode**: Values starting with `ENC(...)` are decrypted, others are encrypted
- **Multi-environment support**: Process multiple environments simultaneously
- **Dual backend**: Supports both Docker and Maven-based encryption

### 🎨 User Interface
- **Dark theme**: Matches Auger platform styling
- **Environment selection**: Dev, Test, Staging, Local, Prod
- **Bulk operations**: Process all selected environments at once
- **Copy to clipboard**: One-click copy for each environment result
- **Status feedback**: Real-time status updates and error messages

### 🔑 Key Management
- **Auto-loading**: Keys loaded from `.env` file or environment variables
- **Visual indicators**: Disabled environments show "(no key)" label
- **Secure handling**: Keys never displayed in UI

## Configuration

### Option 1: Using Docker (Recommended)

Add to your `.env` file:

```bash
# Docker Image
CRYPTKEEPER_DOCKER_IMAGE=artifactory.helix.gsa.gov/gs-assist-docker-repo/cryptkeeper:release-main-latest

# Environment Keys
DEV_CRYPTKEEPER_KEY=your_dev_key_here
TEST_CRYPTKEEPER_KEY=your_test_key_here
STAGING_CRYPTKEEPER_KEY=your_staging_key_here
LOCAL_CRYPTKEEPER_KEY=$ecr3t
PROD_CRYPTKEEPER_KEY=your_prod_key_here
```

**Requirements:**
- Docker must be installed and running
- Access to the cryptkeeper Docker image

### Option 2: Using Maven (Fallback)

If `CRYPTKEEPER_DOCKER_IMAGE` is not set, the widget falls back to Maven:

**Requirements:**
- Maven installed
- Cryptkeeper repository cloned locally
- Repository must contain `pom.xml` with Jasypt plugin

The widget searches for cryptkeeper in:
- `../cryptkeeper` (relative to current directory)
- `~/repos/cryptkeeper`
- `~/workspace/cryptkeeper`
- Custom paths can be added to `_find_cryptkeeper_repo()` method

## Usage

### Encrypting a Value

1. **Select environments** (e.g., Dev, Staging)
2. **Enter plaintext value** in input box:
   ```
   mySecretPassword123
   ```
3. **Click "🔒 Encrypt / 🔓 Decrypt"**
4. **Results appear** for each selected environment:
   ```
   DEV:     ENC(8xj2k4n6m8p0q2s4t6u8v0w2y4z6a8b0)
   STAGING: ENC(9ym3l5o7n9q1r3s5u7v9w1x3z5a7c9d1)
   ```
5. **Click "📋 Copy"** to copy result to clipboard

### Decrypting a Value

1. **Select environments**
2. **Enter encrypted value** (must start with `ENC(` and end with `)`):
   ```
   ENC(8xj2k4n6m8p0q2s4t6u8v0w2y4z6a8b0)
   ```
3. **Click "🔒 Encrypt / 🔓 Decrypt"**
4. **Decrypted value appears**:
   ```
   DEV: mySecretPassword123
   ```

### Bulk Operations

Process multiple environments at once:
1. Check all desired environments (Dev, Test, Staging, etc.)
2. Enter value once
3. Get results for all environments simultaneously

## Technical Details

### Architecture

**Docker Method:**
```bash
docker run --rm -i \
  -e CRYPTKEEPER_KEY={key} \
  -e CRYPTKEEPER_VALUE={value} \
  {image} encrypt-value
```

**Maven Method:**
```bash
mvn jasypt:encrypt-value \
  -Djasypt.encryptor.password={key} \
  -Djasypt.plugin.value={value}
```

### Error Handling

| Error | Cause | Solution |
|-------|-------|----------|
| "No key configured" | Missing key in .env | Add `{ENV}_CRYPTKEEPER_KEY` to .env |
| "Docker encryption failed" | Docker not running or image not found | Start Docker, pull image |
| "Cryptkeeper repository not found" | Maven fallback can't find repo | Clone cryptkeeper or set DOCKER_IMAGE |
| "Maven encryption failed" | Maven or plugin issue | Check Maven installation, run `mvn clean` |

### File Structure

```
ui/widgets/cryptkeeper.py  - Main widget implementation (525 lines)
.env                       - Configuration and keys
```

### Color Scheme

Following Auger platform theme:
- Background: `#1e1e1e`, `#252526`, `#2d2d2d`
- Text: `#e0e0e0`
- Accent: `#007acc` (blue)
- Success: `#4ec9b0` (teal)
- Error: `#f44747` (red)
- Warning: `#ce9178` (orange)

## Security Best Practices

### DO ✅
- Store keys in `.env` file (excluded from git)
- Use environment variables for keys
- Rotate keys regularly
- Use different keys per environment
- Test encryption/decryption before production use

### DON'T ❌
- Hardcode keys in source code
- Commit `.env` file to git
- Share keys via email or chat
- Reuse same key across environments
- Store decrypted values in version control

## Comparison: Old vs New

### Old (cryptkeeper-ui.py)
- 113 lines
- Basic Tkinter styling
- Placeholder keys/image URL
- Hardcoded environment list
- No clipboard copy
- No Maven fallback

### New (Cryptkeeper Widget)
- 525 lines
- Full Auger dark theme
- Auto-loads keys from .env
- Configurable environments
- One-click copy per environment
- Docker + Maven dual backend
- Better error handling
- Hot reload support
- Integrated into platform

## Troubleshooting

**Widget not appearing in menu?**
- Wait 1-2 seconds for hot reload
- Check logs: `tail -20 logs/app.log`
- Restart app: `./auger restart`

**"No key configured" for all environments?**
- Check `.env` file exists
- Verify key format: `{ENV}_CRYPTKEEPER_KEY=value`
- Restart app to reload .env

**Docker timeout or connection error?**
- Verify Docker is running: `docker ps`
- Test image access: `docker pull {image}`
- Check network/VPN if using private registry

**Results show "❌ Error"?**
- Check key is correct for that environment
- Verify encrypted value format: `ENC(...)`
- Check Docker/Maven logs for details

## Future Enhancements

Potential improvements:
- **File encryption**: Encrypt/decrypt entire property files
- **Batch mode**: Process multiple values from CSV
- **Key rotation**: Automated re-encryption with new keys
- **History**: Track encryption operations
- **Validation**: Pre-flight checks for keys and backends
- **Export**: Save results to file
