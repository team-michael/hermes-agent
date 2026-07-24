# Icons (SF Symbols)

Use SF Symbols for native feel. Never use FontAwesome or Ionicons.

## Basic Usage

```tsx
import { Image } from "expo-image";
import { colors } from "@/theme/colors";

<Image
  source="sf:square.and.arrow.down"
  tintColor={colors.label as string}
  contentFit="contain"
  style={{ width: 16, height: 16 }}
  accessibilityLabel="Download"
/>;
```

## Props

```tsx
<Image
  source="sf:star.fill"                // SF Symbol source (required on iOS)
  tintColor={colors.label as string}  // Semantic color cast for expo-image
  contentFit="contain"               // Keep the symbol aspect ratio
  style={{ width: 24, height: 24 }}   // Size explicitly with width and height
  accessibilityLabel="Favorite"      // Required when the icon conveys meaning
/>
```

`expo-image` does not expose SF Symbol weight or scale props. Choose an appropriate
symbol variant, size it explicitly, and use a platform fallback when a specific
weight is essential.

## Common Icons

### Navigation & Actions
- `house.fill` - home
- `gear` - settings
- `magnifyingglass` - search
- `plus` - add
- `xmark` - close
- `chevron.left` - back
- `chevron.right` - forward
- `arrow.left` - back arrow
- `arrow.right` - forward arrow

### Media
- `play.fill` - play
- `pause.fill` - pause
- `stop.fill` - stop
- `backward.fill` - rewind
- `forward.fill` - fast forward
- `speaker.wave.2.fill` - volume
- `speaker.slash.fill` - mute

### Camera
- `camera` - camera
- `camera.fill` - camera filled
- `arrow.triangle.2.circlepath` - flip camera
- `photo` - gallery/photos
- `bolt` - flash
- `bolt.slash` - flash off

### Communication
- `message` - message
- `message.fill` - message filled
- `envelope` - email
- `envelope.fill` - email filled
- `phone` - phone
- `phone.fill` - phone filled
- `video` - video call
- `video.fill` - video call filled

### Social
- `heart` - like
- `heart.fill` - liked
- `star` - favorite
- `star.fill` - favorited
- `hand.thumbsup` - thumbs up
- `hand.thumbsdown` - thumbs down
- `person` - profile
- `person.fill` - profile filled
- `person.2` - people
- `person.2.fill` - people filled

### Content Actions
- `square.and.arrow.up` - share
- `square.and.arrow.down` - download
- `doc.on.doc` - copy
- `trash` - delete
- `pencil` - edit
- `folder` - folder
- `folder.fill` - folder filled
- `bookmark` - bookmark
- `bookmark.fill` - bookmarked

### Status & Feedback
- `checkmark` - success/done
- `checkmark.circle.fill` - completed
- `xmark.circle.fill` - error/failed
- `exclamationmark.triangle` - warning
- `info.circle` - info
- `questionmark.circle` - help
- `bell` - notification
- `bell.fill` - notification filled

### Misc
- `ellipsis` - more options
- `ellipsis.circle` - more in circle
- `line.3.horizontal` - menu/hamburger
- `slider.horizontal.3` - filters
- `arrow.clockwise` - refresh
- `location` - location
- `location.fill` - location filled
- `map` - map
- `mappin` - pin
- `clock` - time
- `calendar` - calendar
- `link` - link
- `nosign` - block/prohibited

## Animated Symbols

```tsx
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withSequence,
  withSpring,
} from "react-native-reanimated";
import { Image } from "expo-image";

const AnimatedImage = Animated.createAnimatedComponent(Image);
const scale = useSharedValue(1);
const animatedStyle = useAnimatedStyle(() => ({ transform: [{ scale: scale.value }] }));

scale.value = withSequence(withSpring(1.18), withSpring(1));

<AnimatedImage
  source="sf:checkmark.circle"
  style={[{ width: 24, height: 24 }, animatedStyle]}
  accessibilityLabel="Completed"
/>
```

### Animation Effects

Animate the `expo-image` component with Reanimated layout, scale, opacity, or
rotation transitions. Keep motion brief, respect reduced-motion preferences,
and do not rely on symbol-specific animation APIs.

## Symbol Weights

```tsx
<Image source="sf:star" style={{ width: 24, height: 24 }} />
<Image source="sf:star.fill" style={{ width: 24, height: 24 }} />
```

When visual weight must match nearby text precisely, choose the closest SF
Symbol variant or provide a reviewed local fallback asset. Do not add a second
symbol-rendering package only to select weights.

## Symbol Scales

```tsx
<Image source="sf:star" style={{ width: 16, height: 16 }} />
<Image source="sf:star" style={{ width: 24, height: 24 }} />
<Image source="sf:star" style={{ width: 32, height: 32 }} />
```

## Multicolor Symbols

Some symbols support multiple colors:

```tsx
<Image
  source="sf:cloud.sun.rain.fill"
  style={{ width: 32, height: 32 }}
  accessibilityLabel="Rainy weather"
/>
```

Do not set `tintColor` when the platform should preserve a symbol's native
multicolor rendering. Verify the result on the targeted iOS version.

## Cross-Platform Fallback

SF Symbol sources are iOS-specific. Provide a reviewed local image for Android
and web while keeping the same accessible name and dimensions:

```tsx
const favoriteSource =
  process.env.EXPO_OS === "ios"
    ? "sf:star.fill"
    : require("@/assets/icons/star-fill.png");

<Image
  source={favoriteSource}
  style={{ width: 24, height: 24 }}
  accessibilityLabel="Favorite"
/>;
```

## Finding Symbol Names

1. Use the SF Symbols app on macOS (free from Apple)
2. Search at https://developer.apple.com/sf-symbols/
3. Symbol names use dot notation: `square.and.arrow.up`

## Best Practices

- Always use SF Symbols over vector icon libraries
- Match symbol weight to nearby text weight
- Use `.fill` variants for selected/active states
- Use the cross-platform `colors` helper (see SKILL.md "Colors") for tint to support dark mode
- Keep icons at consistent sizes (16, 20, 24, 32)
- Give meaningful icons an `accessibilityLabel`; mark purely decorative icons as inaccessible
- Verify the reviewed fallback asset on Android and web
