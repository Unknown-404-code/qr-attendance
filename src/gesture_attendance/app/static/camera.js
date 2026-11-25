// Selfie camera helper.
// Live preview via getUserMedia when the page is a secure context (HTTPS or localhost);
// otherwise falls back to <input type=file capture=user>, which opens the front camera on phones.
const SelfieCamera = {
  stream: null,
  live: false,

  async start(video) {
    this.live = false;
    if (!(window.isSecureContext && navigator.mediaDevices && navigator.mediaDevices.getUserMedia)) return false;
    try {
      if (!this.stream) {
        this.stream = await navigator.mediaDevices.getUserMedia({
          audio: false, video: { facingMode: "user", width: { ideal: 1920 }, height: { ideal: 1440 } } });
      }
      video.srcObject = this.stream;
      await video.play();
      this.live = true;
    } catch (e) {
      console.warn("camera unavailable, using file capture", e);
    }
    return this.live;
  },

  // Grab the current frame (un-mirrored) as a JPEG blob.
  capture(video, quality = 0.92) {
    const c = document.createElement("canvas");
    c.width = video.videoWidth; c.height = video.videoHeight;
    c.getContext("2d").drawImage(video, 0, 0);
    return new Promise(res => c.toBlob(res, "image/jpeg", quality));
  },

  // Shrink a photo to at most `maxSide` px on the long side (JPEG). Keeps uploads small on slow phone data.
  // If the browser can't read the file (for example HEIC on some phones), send it as is: the server explains.
  async shrink(blob, maxSide = 1280, quality = 0.85) {
    let bmp;
    try { bmp = await createImageBitmap(blob, { imageOrientation: "from-image" }); } catch (e) { return blob; }
    const s = Math.min(1, maxSide / Math.max(bmp.width, bmp.height));
    if (s === 1 && blob.type === "image/jpeg" && blob.size < 1.5e6) { bmp.close && bmp.close(); return blob; }
    const c = document.createElement("canvas");
    c.width = Math.round(bmp.width * s); c.height = Math.round(bmp.height * s);
    c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
    bmp.close && bmp.close();
    return new Promise(res => c.toBlob(b => res(b || blob), "image/jpeg", quality));
  },

  stop() {
    if (this.stream) this.stream.getTracks().forEach(t => t.stop());
    this.stream = null; this.live = false;
  },
};
