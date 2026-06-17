# Bundled binaries

This folder is filled by `npm run fetch:go-ios` (also runs automatically as
part of `npm run build`). Layout after a fetch:

```
resources/bin/
├── windows/ios.exe
├── darwin/ios
└── linux/ios            (optional)
```

`go-ios` is downloaded from GitHub releases at the version pinned in
`scripts/fetch-go-ios.js`. Update `GO_IOS_VERSION` there when Apple changes
their iOS protocol and a newer build is required.

The Electron build copies this folder into the installer via
`extraResources`, so end users never have to install go-ios manually.
