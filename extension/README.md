# Chrome extension

In Chrome, open `chrome://extensions`, enable Developer mode, select **Load unpacked**, and choose this `extension/` directory. Chrome installation is a separate browser step. Installing the desktop app does not install or enable the extension.

The extension uses the local Local Voice service at `127.0.0.1:5517` by default. To add a language, open **Model Manager** in the Local Voice desktop app and approve its download there. The extension cannot download or remove models. A missing voice or model needs desktop setup, not a browser permission change. On Linux, the shared service can run without the desktop window. On macOS, open the desktop app to start its service.
