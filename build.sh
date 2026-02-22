#!/bin/bash

# BunnyBot APK Build Script
# This script automates the APK building process

set -e

echo "================================"
echo "BunnyBot APK Build Script"
echo "================================"

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed. Please install Python 3.11 or higher."
    exit 1
fi

# Check if Java is installed
if ! command -v java &> /dev/null; then
    echo "❌ Java is not installed. Please install JDK 17 or higher."
    exit 1
fi

echo "✅ Python and Java found"

# Install buildozer if not already installed
if ! pip3 show buildozer &> /dev/null; then
    echo "📦 Installing Buildozer..."
    pip3 install buildozer cython
fi

# Set JAVA_HOME
export JAVA_HOME=$(dirname $(dirname $(readlink -f $(which java))))
echo "✅ JAVA_HOME set to: $JAVA_HOME"

# Clean previous builds
echo "🧹 Cleaning previous builds..."
buildozer android clean

# Build the APK
echo "🔨 Building APK..."
buildozer android debug

# Find the APK
APK_FILE=$(find bin -name "*.apk" | head -n 1)

if [ -z "$APK_FILE" ]; then
    echo "❌ APK build failed!"
    exit 1
fi

echo "✅ APK built successfully!"
echo "📦 APK location: $APK_FILE"
echo "📊 APK size: $(du -h $APK_FILE | cut -f1)"
echo ""
echo "================================"
echo "Build Complete!"
echo "================================"
echo ""
echo "To install on your device:"
echo "  adb install -r $APK_FILE"
