# KUVHURA Installation Features - Code Reference

## File Locations

### Modified Files
- **index.html** - Main changes (lines 793-823, 3480-3660)

### Configuration Files (Already Present)
- **manifest.json** - PWA metadata
- **service-worker.js** - Offline functionality
- **apple-touch-icon.png** - iOS icon
- **pwa-192x192.png** - Android/PWA icon
- **pwa-512x512.png** - Splash screen icon

---

## HTML Elements

### 1. Install Button (Navbar)
**Location**: Line ~794

```html
<button type="button" id="pwaInstallBtn" class="btn btn-green nav-btn" 
        style="display:inline-flex; align-items:center; gap:5px; 
               font-size:11px; padding:6px 12px; white-space:nowrap; 
               transition: all 0.3s ease; 
               box-shadow: 0 2px 8px rgba(34, 197, 94, 0.3);" 
        onclick="promptPwaInstall()" 
        aria-label="Install KUVHURA Observatory App">
  📲 Install App
</button>
```

**CSS Classes**:
- `.btn` - Base button styling
- `.btn-green` - Green background color
- `.nav-btn` - Makes button visible on mobile

**Attributes**:
- `id="pwaInstallBtn"` - Target for JS manipulation
- `onclick="promptPwaInstall()"` - Triggers installation flow
- `aria-label` - Accessibility

---

### 2. Installation Banner (Sticky Bottom)
**Location**: Line ~823

```html
<div id="pwaInstallBanner" role="status" aria-live="polite" 
     style="display:none; position:fixed; bottom:0; left:0; right:0; 
            z-index:9997; 
            background:linear-gradient(135deg, #072B13 0%, #15803D 100%); 
            color:#F8FAFC; padding:14px 20px; 
            box-shadow:0 -4px 16px rgba(0,0,0,0.5); 
            border-top:2px solid #22C55E; 
            align-items:center; justify-content:space-between; gap:16px; 
            flex-wrap:wrap; 
            animation:slideUp 0.4s ease-out;">
  
  <div style="display:flex; align-items:center; gap:12px;">
    <span style="font-size:18px;">📲</span>
    <div>
      <div style="font-weight:700; font-size:12.5px; margin-bottom:2px;">
        Install KUVHURA Observatory App
      </div>
      <div style="font-size:11px; color:#D1FAE5; opacity:0.9;">
        Get instant access with a one-tap install
      </div>
    </div>
  </div>
  
  <div style="display:flex; gap:8px; align-items:center;">
    <button type="button" class="btn btn-green" 
            style="font-size:11px; padding:7px 14px; margin:0;" 
            onclick="promptPwaInstall()">
      Install Now
    </button>
    <button type="button" 
            style="background:transparent; color:#D1FAE5; border:none; 
                   cursor:pointer; font-size:16px; padding:4px 8px;" 
            onclick="closePwaInstallBanner()" 
            aria-label="Dismiss install banner">
      &times;
    </button>
  </div>
</div>
```

**Features**:
- Fixed positioning at bottom
- Green gradient background
- Flexbox responsive layout
- Slide-up animation
- Dismiss button with X
- Status role for accessibility
- `display:none` by default (shown by JavaScript)

---

### 3. Installation Modal Dialog
**Location**: Line ~799

```html
<div id="pwaInstallModal" role="dialog" aria-modal="true" 
     aria-labelledby="pwaInstallModalTitle" 
     style="display:none; position:fixed; inset:0; z-index:9999; 
            background:rgba(3,7,18,0.78); backdrop-filter:blur(4px); 
            align-items:center; justify-content:center; padding:16px; 
            overflow-y:auto;" 
     onclick="if (event.target === this) closePwaInstallModal();">
  
  <div style="width:100%; max-width:480px; background:#0F172A; 
              border:1px solid #334155; border-top:3px solid #22C55E; 
              border-radius:12px; padding:24px; color:#F8FAFC; 
              box-shadow:0 20px 45px rgba(0,0,0,0.6); margin:auto;">
    
    <!-- Header -->
    <div style="display:flex; justify-content:space-between; 
                align-items:center; gap:12px; margin-bottom:16px;">
      <h3 id="pwaInstallModalTitle" 
          style="margin:0; font-size:16px; font-weight:800; 
                 color:#F8FAFC;">
        📲 Install KUVHURA Observatory
      </h3>
      <button type="button" onclick="closePwaInstallModal()" 
              aria-label="Close install instructions" 
              style="background:transparent; border:1px solid #334155; 
                     color:#94A3B8; border-radius:6px; padding:4px 10px; 
                     cursor:pointer; font-size:14px; font-weight:600;">
        &times;
      </button>
    </div>
    
    <!-- App Store Links (Mobile Only) -->
    <div id="appStoreLinksContainer" 
         style="display:none; margin-bottom:16px; gap:10px; 
                display:flex; flex-direction:column;">
      <p style="margin:0 0 8px; font-size:12px; font-weight:600; 
                color:#D4AF37; text-transform:uppercase; 
                letter-spacing:0.5px;">
        📱 Download Native Apps
      </p>
      
      <!-- iOS App Store -->
      <a href="https://apps.apple.com/search?term=KUVHURA+Observatory" 
         target="_blank" rel="noopener noreferrer" 
         style="display:flex; align-items:center; justify-content:center; 
                gap:8px; padding:12px 16px; background:#1E293B; 
                border:1px solid #334155; border-radius:8px; 
                color:#F8FAFC; text-decoration:none; 
                font-size:12.5px; font-weight:600; 
                transition:all 0.2s;" 
         onmouseover="this.style.background='#334155'" 
         onmouseout="this.style.background='#1E293B'">
        🍎 Get on App Store
      </a>
      
      <!-- Google Play -->
      <a href="https://play.google.com/store/search?q=KUVHURA+Observatory" 
         target="_blank" rel="noopener noreferrer" 
         style="display:flex; align-items:center; justify-content:center; 
                gap:8px; padding:12px 16px; background:#1E293B; 
                border:1px solid #334155; border-radius:8px; 
                color:#F8FAFC; text-decoration:none; 
                font-size:12.5px; font-weight:600; 
                transition:all 0.2s;" 
         onmouseover="this.style.background='#334155'" 
         onmouseout="this.style.background='#1E293B'">
        🤖 Get on Google Play
      </a>
      
      <hr style="margin:12px 0; border:none; border-top:1px solid #334155;">
    </div>
    
    <!-- Instructions (Filled by JavaScript) -->
    <p id="pwaInstallModalIntro" 
       style="margin:0 0 12px; font-size:12.5px; color:#CBD5E1; 
              line-height:1.6;"></p>
    
    <ol id="pwaInstallModalSteps" 
        style="margin:0 0 16px; padding-left:18px; font-size:12.5px; 
               color:#E2E8F0; line-height:1.7;"></ol>
    
    <!-- Footer -->
    <div style="display:flex; gap:8px; justify-content:flex-end; 
                flex-wrap:wrap;">
      <button type="button" class="btn btn-outline" 
              style="font-size:11.5px; padding:8px 16px;" 
              onclick="closePwaInstallModal()">
        Dismiss
      </button>
    </div>
  </div>
</div>
```

**Features**:
- Modal role with `aria-modal="true"`
- Full-screen overlay with blur background
- Responsive max-width
- App store links container (hidden by default, shown for mobile)
- Dynamic instruction container (filled by JS)
- Escape key support
- Overlay click to close

---

### 4. Animation CSS
**Location**: Line ~835

```html
<style>
  @keyframes slideUp {
    from { 
      transform: translateY(100%); 
      opacity: 0; 
    }
    to { 
      transform: translateY(0); 
      opacity: 1; 
    }
  }
</style>
```

---

## JavaScript Functions

### Core Installation Functions

#### 1. `syncPwaInstallButton()`
**Location**: Line ~3475

```javascript
function isRunningStandalonePwa() {
  return Boolean(
    (window.matchMedia && 
     window.matchMedia('(display-mode: standalone)').matches)
    || window.navigator.standalone === true
  );
}

function syncPwaInstallButton() {
  const installBtn = document.getElementById('pwaInstallBtn');
  if (!installBtn) return;
  
  // Hide if already installed
  if (isRunningStandalonePwa()) {
    installBtn.style.display = 'none';
    return;
  }
  
  // Show if browser supports installation
  installBtn.style.display = 'inline-flex';
  
  // Update title based on prompt availability
  const hasNativePrompt = Boolean(window.__kuvhuraDeferredInstallPrompt);
  installBtn.title = hasNativePrompt
    ? 'Install KUVHURA Observatory directly onto your device'
    : 'Install KUVHURA Observatory on your home screen or desktop';
}
```

**Purpose**: Shows/hides the install button based on installation status
**Called**: On page load, when install prompt arrives, when app installs

---

#### 2. `openPwaInstallModal()`
**Location**: Line ~3505

```javascript
function openPwaInstallModal() {
  const modal = document.getElementById('pwaInstallModal');
  const intro = document.getElementById('pwaInstallModalIntro');
  const stepsEl = document.getElementById('pwaInstallModalSteps');
  const appStoreContainer = document.getElementById('appStoreLinksContainer');
  if (!modal || !intro || !stepsEl) return;

  // Detect device type
  const ua = (navigator.userAgent || '').toLowerCase();
  const isIOS = /iphone|ipad|ipod/.test(ua);
  const isAndroid = /android/.test(ua);
  const isInIframe = window.self !== window.top;

  // Show app store links only for mobile
  if (appStoreContainer) {
    appStoreContainer.style.display = isIOS || isAndroid ? 'flex' : 'none';
  }

  let introText = '';
  let steps = [];
  
  // Platform-specific instructions
  if (isInIframe) {
    introText = 'Browsers disable one-tap PWA installation inside embedded preview frames...';
    steps = [
      'Open KUVHURA directly in a full browser tab (outside the preview frame).',
      'Tap the green 📲 Install App button in the top navigation bar...'
    ];
  } else if (isIOS) {
    introText = '✅ Install KUVHURA on iPhone or iPad...';
    steps = [
      'Tap the Share button (box with arrow) at the bottom of Safari.',
      'Scroll down and tap "Add to Home Screen".',
      'Enter a name for the app (default is "KUVHURA") and tap "Add"...'
    ];
  } else if (isAndroid) {
    introText = '✅ Install KUVHURA on Android...';
    steps = [
      'Tap the browser menu button (⋮) in the top-right corner...',
      'Select "Install app", "Add to Home screen", or similar option.',
      'Confirm the installation in the pop-up dialog.'
    ];
  } else {
    introText = '✅ Install KUVHURA as a desktop app...';
    steps = [
      'Look for the Install icon on the right side of the address bar...',
      'Select "Install KUVHURA Observatory" or "Install app"...'
    ];
  }

  // Update modal with platform-specific content
  intro.textContent = introText;
  stepsEl.replaceChildren();
  steps.forEach(stepText => {
    const li = document.createElement('li');
    li.textContent = stepText;
    stepsEl.appendChild(li);
  });
  
  modal.style.display = 'flex';
}
```

**Purpose**: Opens modal with device-specific installation instructions
**Called**: When user clicks Install button/banner

---

#### 3. `promptPwaInstall()`
**Location**: Line ~3565

```javascript
async function promptPwaInstall() {
  const deferred = window.__kuvhuraDeferredInstallPrompt;
  
  // If browser provides native prompt, use it
  if (deferred) {
    try {
      await deferred.prompt();
      const choiceResult = await deferred.userChoice;
      window.__kuvhuraDeferredInstallPrompt = null;
      
      if (choiceResult && choiceResult.outcome === 'accepted') {
        const installBtn = document.getElementById('pwaInstallBtn');
        if (installBtn) installBtn.style.display = 'none';
      } else {
        syncPwaInstallButton();
      }
      return;
    } catch {
      window.__kuvhuraDeferredInstallPrompt = null;
    }
  }
  
  // Fallback: show custom modal with instructions
  openPwaInstallModal();
}
```

**Purpose**: Triggers installation (native or modal)
**Called**: User clicks Install button/banner

---

#### 4. `closePwaInstallModal()`
**Location**: Line ~3585

```javascript
function closePwaInstallModal() {
  const modal = document.getElementById('pwaInstallModal');
  if (modal) modal.style.display = 'none';
}
```

**Purpose**: Closes the installation modal
**Called**: User clicks dismiss button, Escape key, or overlay click

---

#### 5. `closePwaInstallBanner()`
**Location**: Line ~3615

```javascript
function closePwaInstallBanner() {
  const banner = document.getElementById('pwaInstallBanner');
  if (banner) {
    banner.style.display = 'none';
    sessionStorage.setItem('kuvhuraInstallBannerDismissed', 'true');
  }
}
```

**Purpose**: Dismisses banner and prevents reappearance in session
**Called**: User clicks X button on banner

---

#### 6. `showInstallBanner()`
**Location**: Line ~3623

```javascript
function showInstallBanner() {
  // Don't show if already installed, dismissed, or in standalone mode
  if (isRunningStandalonePwa() || 
      sessionStorage.getItem('kuvhuraInstallBannerDismissed')) return;
  
  const banner = document.getElementById('pwaInstallBanner');
  const installBtn = document.getElementById('pwaInstallBtn');
  
  // Only show if button is visible (browser supports installation)
  if (banner && installBtn && installBtn.style.display !== 'none') {
    let showBanner = false;
    
    // Show on scroll
    window.addEventListener('scroll', () => {
      if (!showBanner && window.scrollY > 200) {
        showBanner = true;
        banner.style.display = 'flex';
      }
    }, { once: true });
    
    // Show after 8 seconds
    setTimeout(() => {
      if (!showBanner) {
        showBanner = true;
        banner.style.display = 'flex';
      }
    }, 8000);
  }
}
```

**Purpose**: Smart banner display (scroll or timeout)
**Called**: On page load

---

### Event Listeners

**Location**: Line ~3540-3660

```javascript
// Capture browser's install prompt
window.addEventListener('beforeinstallprompt', function(event) {
  event.preventDefault();
  window.__kuvhuraDeferredInstallPrompt = event;
  if (typeof window.__kuvhuraSyncInstallUi === 'function') {
    window.__kuvhuraSyncInstallUi();
  }
});

// App successfully installed
window.addEventListener('appinstalled', () => {
  window.__kuvhuraDeferredInstallPrompt = null;
  const installBtn = document.getElementById('pwaInstallBtn');
  if (installBtn) installBtn.style.display = 'none';
  const banner = document.getElementById('pwaInstallBanner');
  if (banner) banner.style.display = 'none';
  closePwaInstallModal();
});

// Offline/online status
function syncOfflineBanner() {
  const banner = document.getElementById('pwaOfflineBanner');
  if (!banner) return;
  banner.style.display = navigator.onLine ? 'none' : 'inline-flex';
}
window.addEventListener('online', syncOfflineBanner);
window.addEventListener('offline', syncOfflineBanner);

// Escape key support
window.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') {
    closePwaInstallModal();
    closePwaInstallBanner();
  }
});

// Initialize on page load
syncPwaInstallButton();
syncOfflineBanner();
showInstallBanner();
```

---

## State Management

### Session Storage
```javascript
// Key: kuvhuraInstallBannerDismissed
// Value: 'true' (string)
// Scope: Current browser session only
// Purpose: Prevent banner from reappearing after user dismisses it
// Cleared: When browser/tab closes

// Check if dismissed:
if (sessionStorage.getItem('kuvhuraInstallBannerDismissed')) {
  // Don't show banner
}

// Dismiss:
sessionStorage.setItem('kuvhuraInstallBannerDismissed', 'true');
```

### Window Properties
```javascript
// Deferred install prompt (captured by browser)
window.__kuvhuraDeferredInstallPrompt
// Set by: beforeinstallprompt event
// Used by: promptPwaInstall()
// Cleared by: User accepting/rejecting install

// UI sync function reference
window.__kuvhuraSyncInstallUi
// Set to: syncPwaInstallButton function
// Used by: beforeinstallprompt handler
```

---

## Customization Points

### Change App Store URLs

**iOS App Store** (line ~809):
```javascript
// Change this:
href="https://apps.apple.com/search?term=KUVHURA+Observatory"

// To this (when app is published):
href="https://apps.apple.com/app/KUVHURA-Observatory/id1234567890"
```

**Google Play** (line ~812):
```javascript
// Change this:
href="https://play.google.com/store/search?q=KUVHURA+Observatory"

// To this (when app is published):
href="https://play.google.com/store/apps/details?id=com.kuvhura.observatory"
```

### Change Banner Display Timing

```javascript
// Show after 300px scroll (instead of 200px):
if (!showBanner && window.scrollY > 300) { ... }

// Show after 15 seconds (instead of 8):
setTimeout(() => { ... }, 15000);
```

### Change Banner Display Logic

```javascript
// Never show banner:
function showInstallBanner() { return; }

// Always show banner immediately:
function showInstallBanner() {
  document.getElementById('pwaInstallBanner').style.display = 'flex';
}

// Show only after scroll (not timeout):
// Remove the setTimeout block
```

---

## Testing & Debugging

### Force Installation Prompt
```javascript
// In browser console:
window.__kuvhuraDeferredInstallPrompt?.prompt();
```

### Check Installation Status
```javascript
// In browser console:
// Check if running standalone:
window.matchMedia('(display-mode: standalone)').matches
navigator.standalone  // iOS only

// Check if button is visible:
document.getElementById('pwaInstallBtn').style.display

// Check if banner was dismissed:
sessionStorage.getItem('kuvhuraInstallBannerDismissed')
```

### Simulate Different Platforms
```javascript
// In browser DevTools > Console:
// Spoof iOS:
Object.defineProperty(navigator, 'userAgent', {
  get: () => 'iPhone OS 15_0'
});

// Spoof Android:
Object.defineProperty(navigator, 'userAgent', {
  get: () => 'Android 12'
});

// Reload page after spoofing
location.reload();
```

---

## Performance Notes

- **No external dependencies** - Pure vanilla JavaScript
- **Lazy evaluation** - Functions only run when needed
- **Event delegation** - Uses single overlay click handler
- **Session storage only** - Minimal memory footprint
- **CSS animations** - GPU-accelerated transforms
- **Non-blocking** - All async/await properly handled

---

**Last Updated**: November 2024
**Version**: 1.0.0
**Status**: Production Ready
