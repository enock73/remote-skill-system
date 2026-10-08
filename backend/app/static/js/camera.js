// Photo fields with two choices: use the camera, or upload a file. The captured picture is placed in the normal file input.
(function () {
  document.querySelectorAll('[data-photo-field]').forEach(box => {
    const file = box.querySelector('[data-pf-file]'), cam = box.querySelector('[data-pf-cam]'), video = box.querySelector('[data-pf-video]');
    const prev = box.querySelector('[data-pf-preview]'), img = prev.querySelector('img'), err = box.querySelector('[data-pf-error]');
    const bCam = box.querySelector('[data-pf-mode="camera"]'), bUp = box.querySelector('[data-pf-mode="upload"]');
    let stream = null;
    const say = m => { err.textContent = m || ''; err.classList.toggle('d-none', !m); };
    const stop = () => { if (stream) { stream.getTracks().forEach(t => t.stop()); stream = null; } video.srcObject = null; cam.classList.add('d-none'); };
    const mode = m => { bCam.classList.toggle('active', m === 'camera'); bUp.classList.toggle('active', m === 'upload'); file.classList.toggle('d-none', m === 'camera'); };
    const showPreview = f => { if (!f) { prev.classList.add('d-none'); return; } img.src = URL.createObjectURL(f); prev.classList.remove('d-none'); };
    file.addEventListener('change', () => showPreview(file.files[0]));
    bUp.addEventListener('click', () => { stop(); say(''); mode('upload'); file.click(); });
    bCam.addEventListener('click', async () => {
      say('');
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {   // very old browser or no HTTPS: let the phone camera app take it
        file.setAttribute('capture', box.dataset.facing); mode('upload'); say('Live camera is not available here. Tap the file box and choose Camera.'); return;
      }
      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: box.dataset.facing, width: { ideal: 1600 } }, audio: false });
        video.srcObject = stream; await video.play(); cam.classList.remove('d-none'); file.classList.add('d-none'); prev.classList.add('d-none'); mode('camera');
      } catch (e) {
        stop(); mode('upload'); say('Camera blocked or not found. Allow camera access in your browser, or upload a photo instead.');
      }
    });
    box.querySelector('[data-pf-stop]').addEventListener('click', () => { stop(); mode('upload'); });
    box.querySelector('[data-pf-retake]').addEventListener('click', () => { file.value = ''; prev.classList.add('d-none'); bCam.click(); });
    box.querySelector('[data-pf-snap]').addEventListener('click', () => {
      const w = video.videoWidth, h = video.videoHeight; if (!w || !h) { say('Camera is not ready yet. Wait a second and try again.'); return; }
      const k = Math.min(1, 1600 / Math.max(w, h)), c = document.createElement('canvas'); c.width = Math.round(w * k); c.height = Math.round(h * k);
      c.getContext('2d').drawImage(video, 0, 0, c.width, c.height);
      c.toBlob(blob => {
        if (!blob) { say('Could not take the photo. Try again.'); return; }
        const f = new File([blob], box.querySelector('[data-pf-file]').name + '.jpg', { type: 'image/jpeg' }), dt = new DataTransfer(); dt.items.add(f); file.files = dt.files;
        showPreview(f); stop(); mode('upload'); file.classList.add('d-none');
      }, 'image/jpeg', 0.9);
    });
  });
})();

