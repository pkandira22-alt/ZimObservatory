# KUVHURA Observatory App Installation Guide

## Overview

The KUVHURA Observatory now features comprehensive app installation capabilities for both web and native platforms. Users can install the application as a Progressive Web App (PWA) on any device, with native app store options for iOS and Android.

---

## 🎯 Installation Features

### 1. **Install App Button (Navbar)**
- **Location**: Top navigation bar, next to "Connect / Collaborate"
- **Icon**: 📲 Install App
- **Functionality**: 
  - Shows prominently on desktop and mobile devices
  - Automatically hidden when app is already installed (standalone mode)
  - Adapts instructions based on device type (iOS, Android, Desktop, or iframe)

### 2. **Smart Installation Banner**
- **Location**: Bottom of the page (sticky)
- **Trigger**: 
  - Appears after user scrolls 200px down, OR
  - Appears after 8 seconds of initial page load (whichever comes first)
- **Features**:
  - Green gradient design matching KUVHURA branding
  - Quick install button
  - Dismiss button with emoji (×)
  - Dismissed banners don't reappear in the same session
  
### 3. **Installation Modal Dialog**
- **Location**: Center of screen (overlay)
- **Content**: Platform-specific installation steps
- **Device Detection**:
  - **iOS (iPhone/iPad)**: Safari Share sheet instructions
  - **Android**: Chrome menu installation steps
  - **Desktop**: Browser address bar install prompts
  - **Embedded Frame**: Frame-aware instructions

### 4. **App Store Links** (Mobile Devices Only)
- **iOS**: App Store search link (ready for official app listing)
- **Android**: Google Play search link (ready for official app listing)
- **Display**: Only shown on mobile devices in the installation modal

---

## 🔧 Technical Implementation

### HTML Elements

#### Install Button
```html
<button type="button" id="pwaInstallBtn" class="btn btn-green nav-btn" 
        onclick="promptPwaInstall()" aria-label="Install KUVHURA Observatory App">
  📲 Install App
</button>
```

#### Installation Banner
```html
<div id="pwaInstallBanner" role="status" aria-live="polite" 
     style="position:fixed; bottom:0; ...">
  <!-- Sticky banner with Install Now button -->
</div>
```

#### Installation Modal
```html
<div id="pwaInstallModal" role="dialog" aria-modal="true" 
     aria-labelledby="pwaInstallModalTitle" style="display:none; ...">
  <!-- Full-screen overlay with platform-specific instructions -->
</div>
```

### JavaScript Functions

| Function | Purpose |
|----------|---------|
| `promptPwaInstall()` | Triggers installation prompt or opens modal |
| `openPwaInstallModal()` | Shows platform-specific installation instructions |
| `closePwaInstallModal()` | Closes the installation modal |
| `closePwaInstallBanner()` | Hides the sticky banner and prevents re-display |
| `showInstallBanner()` | Shows banner after scroll/delay (auto-triggered on load) |
| `syncPwaInstallButton()` | Hides button when app is already installed |
| `isRunningStandalonePwa()` | Checks if app is running in standalone mode |
| `syncOfflineBanner()` | Shows/hides offline indicator |

### Events

```javascript
// Browser triggers installation prompt
window.addEventListener('beforeinstallprompt', event => {
  window.__kuvhuraDeferredInstallPrompt = event;
  syncPwaInstallButton();
});

// App successfully installed
window.addEventListener('appinstalled', () => {
  // Hide install UI
});

// Online/offline status
window.addEventListener('online', syncOfflineBanner);
window.addEventListener('offline', syncOfflineBanner);

// Escape key closes modals
window.addEventListener('keydown', event => {
  if (event.key === 'Escape') {
    closePwaInstallModal();
    closePwaInstallBanner();
  }
});
```

---

## 📱 Platform-Specific Behavior

### iOS (Safari)
1. User clicks "Install App" button
2. Modal shows Safari-specific instructions:
   - Tap Share button at bottom
   - Scroll and select "Add to Home Screen"
   - Confirm with "Add" button
3. App appears on home screen as native app
4. App Store link provided for native app

**Prerequisites**:
- iOS 11.3+
- Safari browser
- Manifest.json configured ✅

### Android (Chrome/Firefox)
1. User clicks "Install App" button
2. Modal shows browser menu installation steps:
   - Tap menu button (⋮) → "Install app"
   - Confirm installation
3. App launches in standalone mode
4. Google Play link provided for native app

**Prerequisites**:
- Android 5.0+
- Chromium-based browser
- Service Worker registered ✅

### Desktop (Windows/Mac/Linux)
1. User clicks "Install App" button
2. Browser shows install prompt in address bar
3. User selects "Install KUVHURA Observatory"
4. App appears in applications menu/desktop

**Prerequisites**:
- Chrome 68+, Edge 79+, Firefox, Opera
- HTTPS connection ✅

---

## 🎨 Visual Design

### Install Button Styling
- **Color**: Green gradient (#15803D → #16A34A on hover)
- **Size**: 11px font, 6px 12px padding
- **Icon**: 📲 (mobile emoji)
- **Animation**: Smooth color transition on hover
- **Shadow**: Green glow effect

### Installation Banner
- **Position**: Fixed at bottom, full width
- **Background**: Green gradient (072B13 → 15803D)
- **Animation**: Slide up from bottom
- **Layout**: Flexbox with responsive wrapping
- **Close Button**: Top right corner

### Modal Dialog
- **Width**: 480px max (responsive on mobile)
- **Background**: Dark semi-transparent overlay
- **Border**: Green top accent (3px solid)
- **Shadow**: Strong drop shadow
- **Scrollable**: Yes, for long instruction lists

---

## 🚀 Usage Instructions for Users

### Quick Install (All Platforms)
1. Click the **📲 Install App** button in the navigation bar
2. Follow the platform-specific instructions
3. App launches offline-ready on your device

### From Banner
1. Watch for the **green installation banner** at the bottom
2. Click **Install Now** button
3. Follow the same process

### Native Apps (Coming Soon)
- iOS: Search "KUVHURA Observatory" in App Store
- Android: Search "KUVHURA Observatory" on Google Play

---

## 🔐 Offline Capability

When installed, KUVHURA operates offline using:
- **Service Worker**: Caches assets and app shell
- **IndexedDB**: Stores cached data
- **Status Indicator**: "Offline Mode" banner shows when disconnected

---

## 🛠️ Development Notes

### Configuration Files
- **manifest.json**: PWA metadata (name, icons, display mode)
- **service-worker.js**: Offline functionality and caching
- **apple-touch-icon.png**: iOS home screen icon
- **pwa-192x192.png, pwa-512x512.png**: Android/PWA icons

### Testing Installation

**Desktop Chrome**:
```bash
# HTTPS required - use a local HTTPS server or deploy
npm run dev  # Local testing (may not show install prompt without HTTPS)
```

**Mobile Testing**:
1. Deploy to HTTPS domain
2. Open in mobile browser
3. Click "Install App" button
4. Follow platform instructions

**Force PWA Install Prompt** (Chrome DevTools):
```javascript
// In console, manually trigger:
window.__kuvhuraDeferredInstallPrompt?.prompt();
```

---

## 📊 Browser Support

| Browser | Desktop | Mobile | Native Install |
|---------|---------|--------|-----------------|
| Chrome | ✅ | ✅ | ✅ |
| Edge | ✅ | ✅ | ✅ |
| Firefox | ✅ | ✅ | (via extension) |
| Safari | ❌ | ✅ (Share) | Manual Add to Home |
| Opera | ✅ | ✅ | ✅ |

---

## 🔄 Storage Management

**Session Storage** (Installation Banner):
- Key: `kuvhuraInstallBannerDismissed`
- Clears on browser close
- Prevents banner spam in same session

**localStorage** (Potential Future):
- Could persist user preferences
- Remember dismissed state across sessions
- Remember last active section

---

## 🎯 Future Enhancements

- [ ] Native iOS app on App Store
- [ ] Native Android app on Google Play
- [ ] In-app update notifications
- [ ] Custom app launcher menu
- [ ] Personalized dashboard for installed app
- [ ] Deep linking for installed app
- [ ] Share API integration
- [ ] Background sync for data updates

---

## 📝 Customization Guide

### Update App Store Links
In `index.html`, find and update:
```html
<!-- When iOS app is published -->
<a href="https://apps.apple.com/app/KUVHURA-Observatory/id123456789">

<!-- When Android app is published -->
<a href="https://play.google.com/store/apps/details?id=com.kuvhura.observatory">
```

### Change Banner Display Timing
In JavaScript (line ~3625):
```javascript
// Show after 300px scroll instead of 200px:
if (!showBanner && window.scrollY > 300) {

// Show after 15 seconds instead of 8:
setTimeout(() => { ... }, 15000);
```

### Customize Installation Instructions
In `openPwaInstallModal()` function, modify the `steps` array for each platform.

---

## 🐛 Troubleshooting

### Button Not Showing
- Check if app is already installed (standalone mode)
- Ensure browser supports PWA installation
- Verify HTTPS connection
- Check browser DevTools console for errors

### Installation Fails
- Ensure manifest.json is valid
- Verify service-worker.js is registered
- Check HTTPS configuration
- Clear browser cache and retry

### Banner Won't Appear
- Scroll page to trigger banner
- Wait 8 seconds for auto-trigger
- Refresh page if banner was dismissed
- Check sessionStorage for dismissal flag

### iOS App Won't Install
- Use Safari on iOS 11.3+
- Ensure internet connection
- Check if app is already added
- Verify apple-touch-icon.png is accessible

---

## 📞 Support

For installation issues:
1. Check browser console (F12) for errors
2. Try alternative browser
3. Clear cache and cookies
4. Contact support with:
   - Device type (iOS/Android/Desktop)
   - Browser name and version
   - Console error messages

---

**Last Updated**: November 2024
**Version**: 1.0.0
**Status**: Active
