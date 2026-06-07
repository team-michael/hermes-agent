# LinkedIn post media extraction from Slack thread links

Use this when a Slack thread contains LinkedIn post URLs and the user asks to inspect attached videos/screenshots, not just page text.

## Pattern

1. Fetch the Slack thread first and extract LinkedIn URLs from message text/previews.
2. Open each individual LinkedIn post in the browser. LinkedIn may first show a sign-in modal; if public content is visible after dismissing the modal, continue. A `200` HTTP status alone is not evidence that media is readable.
3. Extract media URLs from the rendered DOM with browser console:

```js
JSON.stringify({
  url: location.href,
  title: document.title,
  videos: [...document.querySelectorAll('video')].map(v => ({
    src: v.currentSrc || v.src,
    poster: v.poster,
    duration: v.duration,
    currentTime: v.currentTime,
    w: v.videoWidth,
    h: v.videoHeight,
    paused: v.paused,
  })),
  images: [...document.images].map((img, i) => ({
    i,
    alt: img.alt,
    src: img.currentSrc || img.src,
    delayed: img.getAttribute('data-delayed-url'),
    w: img.naturalWidth,
    h: img.naturalHeight,
    ow: img.offsetWidth,
    oh: img.offsetHeight,
  })).filter(x => x.src || x.delayed || x.ow > 100),
  body: document.body.innerText.slice(0, 4000),
})
```

4. For video posts, `video.currentSrc` often contains a signed `https://dms.licdn.com/playlist/...mp4` URL and `poster` contains a cover image. Download with a browser-like user agent if you need frame inspection.
5. For LinkedIn lazy images, the useful URL may be in `data-delayed-url` while `src` is empty. Use that URL for screenshot/GIF download.
6. Use `ffprobe` to get duration/resolution and `ffmpeg -ss ... -frames:v 1` to extract representative frames. For short product demos, 3-4 frames across the duration are usually enough; combine them into a contact sheet and inspect with vision.
7. Summarize separately:
   - post body claims
   - video/screenshot UI evidence
   - what is inaccessible without login (full comments, DM-gated PDFs/Notion/prompt docs)

## Useful commands

```bash
curl -fsSL -A 'Mozilla/5.0' -o media.mp4 'https://dms.licdn.com/...mp4'
ffprobe -v error -show_entries format=duration:stream=width,height,codec_type -of default=nw=1 media.mp4
ffmpeg -hide_banner -loglevel error -y -ss 3 -i media.mp4 -frames:v 1 frame_03.jpg
```

For GIF-like LinkedIn images:

```bash
curl -fsSL -A 'Mozilla/5.0' -o media.gif 'https://media.licdn.com/...'
ffprobe -v error -show_entries format=duration:stream=width,height,nb_frames -of default=nw=1 media.gif
ffmpeg -hide_banner -loglevel error -y -i media.gif -vf 'fps=1,scale=540:-1' frames_%02d.jpg
```

## Pitfalls

- Company `/posts/` pages may authwall even when individual public posts are readable.
- LinkedIn can expose the text snapshot but leave images unloaded; inspect `data-delayed-url` before concluding screenshots are unavailable.
- A LinkedIn preview in Slack may include enough text for the post, but not enough for the media. Browser-rendered DOM is better for `video.currentSrc` and lazy image URLs.
- Keep the user-facing conclusion scoped: “public post body and attached media visible” is different from “DM-gated material is accessible.”
