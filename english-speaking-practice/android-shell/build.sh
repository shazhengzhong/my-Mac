#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
TOOLCHAIN="$ROOT_DIR/toolchain"
JAVA_HOME="$TOOLCHAIN/jdk-21.0.2.jdk/Contents/Home"
SDK_ROOT="$TOOLCHAIN/android-sdk"
BUILD_TOOLS="$SDK_ROOT/build-tools/35.0.0"
ANDROID_JAR="$SDK_ROOT/platforms/android-35/android.jar"
BUILD_DIR="$ROOT_DIR/build"

export JAVA_HOME
export PATH="$JAVA_HOME/bin:$BUILD_TOOLS:$PATH"

rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR/classes" "$BUILD_DIR/dex" "$BUILD_DIR/gen"

echo "Compiling resources..."
aapt2 compile --dir "$ROOT_DIR/res" -o "$BUILD_DIR/res.zip"

echo "Linking resources..."
aapt2 link \
  -o "$BUILD_DIR/unsigned.apk" \
  -I "$ANDROID_JAR" \
  --manifest "$ROOT_DIR/AndroidManifest.xml" \
  --java "$BUILD_DIR/gen" \
  --min-sdk-version 24 \
  --target-sdk-version 35 \
  "$BUILD_DIR/res.zip"

echo "Compiling Java..."
javac \
  -source 8 \
  -target 8 \
  -encoding UTF-8 \
  -classpath "$ANDROID_JAR" \
  -d "$BUILD_DIR/classes" \
  "$ROOT_DIR/src/com/family/englishdiary/"*.java

echo "Dexing..."
d8 \
  --lib "$ANDROID_JAR" \
  --min-api 24 \
  --output "$BUILD_DIR/dex" \
  "$BUILD_DIR/classes/com/family/englishdiary/"*.class

echo "Adding classes.dex..."
(cd "$BUILD_DIR/dex" && zip -q -u "$BUILD_DIR/unsigned.apk" classes.dex)

if [ ! -f "$ROOT_DIR/keystore/debug.keystore" ]; then
  echo "Creating debug keystore..."
  keytool -genkeypair \
    -keystore "$ROOT_DIR/keystore/debug.keystore" \
    -storepass android \
    -keypass android \
    -alias androiddebugkey \
    -keyalg RSA \
    -keysize 2048 \
    -validity 10000 \
    -dname "CN=Family English Diary, OU=Home, O=Home, L=Home, ST=Home, C=CN"
fi

echo "Aligning..."
zipalign -f 4 "$BUILD_DIR/unsigned.apk" "$BUILD_DIR/aligned.apk"

echo "Signing..."
apksigner sign \
  --ks "$ROOT_DIR/keystore/debug.keystore" \
  --ks-key-alias androiddebugkey \
  --ks-pass pass:android \
  --key-pass pass:android \
  --out "$BUILD_DIR/family-diary.apk" \
  "$BUILD_DIR/aligned.apk"

apksigner verify --verbose "$BUILD_DIR/family-diary.apk"
echo
echo "APK: $BUILD_DIR/family-diary.apk"
ls -lh "$BUILD_DIR/family-diary.apk"
