# Building and Releasing BunnyBot APK

## Overview

This guide provides instructions for building the BunnyBot Android APK and setting up automated releases on GitHub.

## Option 1: Manual Local Build (Recommended for Testing)

### Prerequisites

- Python 3.11+
- Java Development Kit (JDK) 17+
- Android SDK (API 33 or higher)
- Android NDK (version 25b)

### Installation Steps

1. **Install Buildozer:**
   ```bash
   pip install buildozer cython
   ```

2. **Install system dependencies (Ubuntu/Debian):**
   ```bash
   sudo apt-get update
   sudo apt-get install -y \
     build-essential git zip unzip openjdk-17-jdk \
     autoconf libtool pkg-config zlib1g-dev libncurses-dev \
     libbz2-dev libssl-dev libffi-dev libsqlite3-dev \
     libxml2-dev libxslt1-dev libjpeg-dev libpng-dev \
     libfreetype6-dev libharfbuzz-dev libwebp-dev \
     libtiff-dev libjasper-dev libopenexr-dev libtbb-dev
   ```

3. **Set JAVA_HOME:**
   ```bash
   export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
   ```

4. **Build the APK:**
   ```bash
   buildozer android debug
   ```

5. **Find your APK:**
   The compiled APK will be located at:
   ```
   bin/bunnybot-1.0.0-debug.apk
   ```

## Option 2: Automated GitHub Actions (Recommended for Production)

### Setup Instructions

1. Go to your repository: https://github.com/study11dav-max/Bunny-run

2. Click on **Settings** → **Actions** → **General**

3. Under "Workflow permissions", select:
   - ✅ **Read and write permissions**
   - ✅ **Allow GitHub Actions to create and approve pull requests**

4. Create the workflow file manually:
   - Click **Add file** → **Create new file**
   - Name it: `.github/workflows/build-apk.yml`
   - Paste the content from the workflow template below

5. Commit the file

### Workflow Template

```yaml
name: Build APK and Release

on:
  push:
    branches: [ main ]
  workflow_dispatch:

jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: write

    steps:
    - name: Checkout code
      uses: actions/checkout@v3

    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.11'

    - name: Install system dependencies
      run: |
        sudo apt-get update
        sudo apt-get install -y \
          build-essential git zip unzip openjdk-17-jdk \
          autoconf libtool pkg-config zlib1g-dev libncurses-dev \
          libbz2-dev libssl-dev libffi-dev libsqlite3-dev \
          libxml2-dev libxslt1-dev libjpeg-dev libpng-dev \
          libfreetype6-dev libharfbuzz-dev libwebp-dev \
          libtiff-dev libjasper-dev libopenexr-dev libtbb-dev

    - name: Install Python dependencies
      run: |
        python -m pip install --upgrade pip
        pip install buildozer cython

    - name: Set JAVA_HOME
      run: echo "JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64" >> $GITHUB_ENV

    - name: Build APK
      run: |
        cd ${{ github.workspace }}
        buildozer android debug 2>&1 | tee build.log

    - name: Find APK file
      id: find_apk
      run: |
        APK_FILE=$(find ${{ github.workspace }}/bin -name "*.apk" -type f | head -n 1)
        if [ -z "$APK_FILE" ]; then
          echo "APK not found!"
          cat ${{ github.workspace }}/build.log
          exit 1
        fi
        echo "apk_path=$APK_FILE" >> $GITHUB_OUTPUT
        echo "apk_name=$(basename $APK_FILE)" >> $GITHUB_OUTPUT

    - name: Create Release
      uses: softprops/action-gh-release@v1
      if: github.event_name == 'push' && github.ref == 'refs/heads/main'
      with:
        tag_name: v${{ github.run_number }}-${{ github.run_id }}
        name: Release Build ${{ github.run_number }}
        draft: false
        prerelease: false
        files: ${{ steps.find_apk.outputs.apk_path }}
      env:
        GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}

    - name: Upload build log on failure
      if: failure()
      uses: actions/upload-artifact@v3
      with:
        name: build-log
        path: ${{ github.workspace }}/build.log
```

## Troubleshooting

### Build Fails with "Java not found"
- Ensure JDK 17 is installed
- Set `JAVA_HOME` environment variable correctly

### APK not found after build
- Check the build log for errors
- Ensure all dependencies are installed
- Try cleaning the build: `buildozer android clean`

### GitHub Actions permission denied
- Go to repository Settings → Actions → General
- Enable "Read and write permissions"

## File Structure

```
Bunny-run/
├── main.py                 # App entry point
├── buildozer.spec          # Build configuration
├── requirements.txt        # Python dependencies
├── build.gradle            # Gradle configuration
├── core/
│   ├── vision.py          # Vision detection module
│   ├── controller.py      # Android control module
│   ├── wizard.py          # Configuration management
│   ├── vision_auto.py     # Auto UI detection
│   └── permissions.py     # Permission handling
├── ui/
│   └── dashboard.py       # UI dashboard
└── templates/
    ├── starting_btn.png
    ├── winning_btn.png
    ├── ending_btn.png
    └── fence_ref.png
```

## Next Steps

1. Ensure all template images are in the `templates/` directory
2. Update the `buildozer.spec` with your app icon if needed
3. Test locally first before setting up GitHub Actions
4. Once working, push to main branch to trigger automated builds

## Support

For issues or questions, refer to:
- Buildozer Documentation: https://buildozer.readthedocs.io/
- Kivy Documentation: https://kivy.org/doc/stable/
- GitHub Actions Documentation: https://docs.github.com/en/actions
