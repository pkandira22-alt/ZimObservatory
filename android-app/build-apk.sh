#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$ROOT_DIR/android-app"
BUILD_DIR="$APP_DIR/build"
GEN_DIR="$BUILD_DIR/gen"
OBJ_DIR="$BUILD_DIR/obj"
OUT_DIR="$ROOT_DIR/public/downloads"
APK_OUT="$OUT_DIR/kuvhura-observatory.apk"

ANDROID_JAR="/usr/lib/android-sdk/platforms/android-23/android.jar"
if [[ ! -f "$ANDROID_JAR" ]]; then
  ANDROID_JAR="$(find /usr/lib/android-sdk /usr/share/java -name 'android.jar' 2>/dev/null | head -n 1 || true)"
fi
if [[ -z "${ANDROID_JAR:-}" || ! -f "$ANDROID_JAR" ]]; then
  echo "ERROR: android.jar not found. Install android-sdk-platform-23." >&2
  exit 1
fi

KEYSTORE_DIR="${KUVHURA_KEYSTORE_DIR:-/tmp/kuvhura-android-keystore}"
KEYSTORE_PATH="${KUVHURA_KEYSTORE_PATH:-$KEYSTORE_DIR/kuvhura-release.jks}"
KEY_ALIAS="${KUVHURA_KEY_ALIAS:-kuvhura}"
KEY_PASS="${KUVHURA_KEY_PASS:-kuvhura2026release}"

rm -rf "$BUILD_DIR"
mkdir -p "$GEN_DIR" "$OBJ_DIR" "$OUT_DIR" "$KEYSTORE_DIR"

# 1. Generate crisp multi-density launcher PNG icons from pwa-512x512.png using Java ImageIO
cat > "$BUILD_DIR/ResizeIcons.java" <<'EOF'
import java.awt.Graphics2D;
import java.awt.RenderingHints;
import java.awt.image.BufferedImage;
import java.io.File;
import javax.imageio.ImageIO;

public class ResizeIcons {
    public static void main(String[] args) throws Exception {
        File srcFile = new File(args[0]);
        File resDir = new File(args[1]);
        BufferedImage src = ImageIO.read(srcFile);
        if (src == null) throw new IllegalStateException("Could not read source icon: " + srcFile);
        Object[][] specs = {
            {"mipmap-mdpi", 48},
            {"mipmap-hdpi", 72},
            {"mipmap-xhdpi", 96},
            {"mipmap-xxhdpi", 144},
            {"mipmap-xxxhdpi", 192}
        };
        for (Object[] spec : specs) {
            File dir = new File(resDir, (String) spec[0]);
            dir.mkdirs();
            int size = (Integer) spec[1];
            BufferedImage dst = new BufferedImage(size, size, BufferedImage.TYPE_INT_ARGB);
            Graphics2D g = dst.createGraphics();
            g.setRenderingHint(RenderingHints.KEY_INTERPOLATION, RenderingHints.VALUE_INTERPOLATION_BICUBIC);
            g.setRenderingHint(RenderingHints.KEY_RENDERING, RenderingHints.VALUE_RENDER_QUALITY);
            g.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON);
            g.drawImage(src, 0, 0, size, size, null);
            g.dispose();
            ImageIO.write(dst, "PNG", new File(dir, "ic_launcher.png"));
        }
    }
}
EOF

javac "$BUILD_DIR/ResizeIcons.java"
java -cp "$BUILD_DIR" ResizeIcons "$ROOT_DIR/pwa-512x512.png" "$APP_DIR/res"

# 2. Generate R.java and initial resource package
aapt package -f -m \
  -J "$GEN_DIR" \
  -M "$APP_DIR/AndroidManifest.xml" \
  -S "$APP_DIR/res" \
  -I "$ANDROID_JAR"

# 3. Compile Java sources targeting Java 8 bytecode for Dalvik/ART compatibility
javac -source 1.8 -target 1.8 \
  -bootclasspath "$ANDROID_JAR" \
  -classpath "$ANDROID_JAR" \
  -d "$OBJ_DIR" \
  "$GEN_DIR/org/kuvhura/observatory/R.java" \
  "$APP_DIR/src/org/kuvhura/observatory/MainActivity.java"

# 4. Convert Java bytecode to classes.dex
DX_BIN="$(command -v dx || command -v dalvik-exchange || echo /usr/lib/android-sdk/build-tools/debian/dx)"
"$DX_BIN" --dex --output="$BUILD_DIR/classes.dex" "$OBJ_DIR"

# 5. Package unsigned APK with compiled resources
aapt package -f \
  -M "$APP_DIR/AndroidManifest.xml" \
  -S "$APP_DIR/res" \
  -I "$ANDROID_JAR" \
  -F "$BUILD_DIR/app-unsigned.apk"

# 6. Add classes.dex into APK root
(cd "$BUILD_DIR" && aapt add -f app-unsigned.apk classes.dex >/dev/null)

# 7. Align APK on 4-byte boundaries (required before v2/v3 signing)
zipalign -p -f 4 "$BUILD_DIR/app-unsigned.apk" "$BUILD_DIR/app-aligned.apk"

# 8. Create signing keystore if not already present
if [[ ! -f "$KEYSTORE_PATH" ]]; then
  keytool -genkeypair -v \
    -keystore "$KEYSTORE_PATH" \
    -storetype PKCS12 \
    -alias "$KEY_ALIAS" \
    -keyalg RSA \
    -keysize 2048 \
    -validity 10000 \
    -storepass "$KEY_PASS" \
    -keypass "$KEY_PASS" \
    -dname "CN=KUVHURA Observatory, OU=Civic Analytics, O=KUVHURA, L=Harare, C=ZW" >/dev/null 2>&1
fi

# 9. Sign APK with v1 + v2 + v3 schemes and verify
apksigner sign \
  --ks "$KEYSTORE_PATH" \
  --ks-key-alias "$KEY_ALIAS" \
  --ks-pass "pass:$KEY_PASS" \
  --key-pass "pass:$KEY_PASS" \
  --v1-signing-enabled true \
  --v2-signing-enabled true \
  --v3-signing-enabled true \
  --out "$APK_OUT" \
  "$BUILD_DIR/app-aligned.apk"

apksigner verify --verbose --print-certs "$APK_OUT"
rm -rf "$BUILD_DIR"

ls -lh "$APK_OUT"
sha256sum "$APK_OUT"
