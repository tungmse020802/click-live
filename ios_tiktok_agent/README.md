# TikTok Agent for iPhone

SwiftUI companion app for opening TikTok links and recognizing the treasure-box
object from a selected screenshot.

The matcher ignores the bottom 35 percent of the comparison image, so countdown
text is excluded.

See [IOS_TIKTOK_AGENT_PLAN.md](../IOS_TIKTOK_AGENT_PLAN.md).

Build an unsigned device bundle:

```bash
xcodebuild -project TikTokAgent.xcodeproj -target TikTokAgent \
  -sdk iphoneos -configuration Debug CODE_SIGNING_ALLOWED=NO build
```
