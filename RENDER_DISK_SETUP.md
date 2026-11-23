# Render Persistent Disk Configuration

## Overview
This document describes how the ZimObservatory project is configured to use Render's persistent disk for storing telemetry data.

## Configuration Details

### Environment
- **Service**: zimobservatory-backend (Node.js)
- **Storage Directory**: `/var/data`
- **Storage Variable**: `TIMELINE_STORAGE_DIR`
- **Disk Name**: `timeline-storage`
- **Disk Size**: 1 GB

### File Structure
```
/var/data/
└── daily_telemetry_snapshots.json
```

## How It Works

### 1. Render Configuration (render.yaml)
The persistent disk is configured in `render.yaml` under the `zimobservatory-backend` service:

```yaml
disk:
  name: timeline-storage
  mountPath: /var/data
  sizeGB: 1
```

This tells Render to:
- Create a persistent disk named `timeline-storage`
- Mount it at `/var/data`
- Allocate 1 GB of storage

### 2. Environment Variables
The service sets the `TIMELINE_STORAGE_DIR` environment variable:

```yaml
envVars:
  - key: TIMELINE_STORAGE_DIR
    value: /var/data
```

This tells the Node.js application where to store telemetry data.

### 3. Application Code (server.js)
The application:
- Reads the `TIMELINE_STORAGE_DIR` environment variable on startup
- Automatically creates the directory if it doesn't exist (with `recursive: true`)
- Stores telemetry snapshots at `/var/data/daily_telemetry_snapshots.json`
- Falls back to local uploads directory if the environment variable is not set

## Testing the Setup

### Local Development
On your local machine (before deployment to Render):

```bash
# Create the directory structure
mkdir -p /var/data

# Test the path
ls -lh /var/data/

# Or with the environment variable
export TIMELINE_STORAGE_DIR=/var/data
ls -lh "$TIMELINE_STORAGE_DIR/daily_telemetry_snapshots.json"
```

### On Render
After deployment, you can:

1. **SSH into the Render service** (if enabled)
2. **Check the directory exists**:
   ```bash
   ls -lh /var/data/
   ls -lh "$TIMELINE_STORAGE_DIR/daily_telemetry_snapshots.json"
   ```

3. **Check the logs** in Render dashboard for any startup errors

## Important Notes

### Persistence
- Data stored in `/var/data/` is **persistent** across deployments and restarts
- Deleting the disk in Render will delete all stored data

### Scaling
- If you scale to multiple instances, only one instance can write to the disk at a time
- The disk is **not** shared across multiple instances
- Current setup assumes single-instance deployment

### Disk Size Increase
If you need more than 1 GB:
1. Update `sizeGB` in `render.yaml`
2. Redeploy to Render

## Deployment Steps

1. **Commit changes**:
   ```bash
   git add render.yaml server.js
   git commit -m "Configure persistent disk for telemetry storage"
   ```

2. **Push to GitHub**:
   ```bash
   git push origin main
   ```

3. **Render will automatically redeploy** (if connected to GitHub)

4. **Monitor the deployment** in the Render dashboard

## Troubleshooting

### "TIMELINE_STORAGE_DIR must be an absolute directory path"
- Ensure `TIMELINE_STORAGE_DIR` in render.yaml is an absolute path starting with `/`
- Current value: `/var/data` ✓

### Directory doesn't exist
- The application now automatically creates the directory
- If creation fails, check Render logs for permission issues

### File not found
- First deployment: `daily_telemetry_snapshots.json` won't exist until the first telemetry snapshot is written
- Subsequent deployments: the file should persist

### Permission denied
- Check that the Node.js process has write permissions to `/var/data`
- This should be automatic with Render's setup

## References
- [Render Disks Documentation](https://render.com/docs/disks)
- [Render Environment Variables](https://render.com/docs/environment-variables)
