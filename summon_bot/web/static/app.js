import * as THREE from "https://cdn.jsdelivr.net/npm/three@0.170.0/build/three.module.js";

const tg = window.Telegram?.WebApp;
if (tg) {
  tg.ready();
  tg.expand();
}

const title = document.getElementById("title");
const meta = document.getElementById("meta");
const list = document.getElementById("cards");
const badge = document.getElementById("badge");

const scene = new THREE.Scene();
scene.fog = new THREE.FogExp2(0x0b0a10, 0.035);

const camera = new THREE.PerspectiveCamera(55, window.innerWidth / window.innerHeight, 0.1, 100);
camera.position.set(0, 1.2, 6);

const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setSize(window.innerWidth, window.innerHeight);
document.getElementById("canvas-wrap").appendChild(renderer.domElement);

const light = new THREE.PointLight(0x8fd3ff, 2, 20);
light.position.set(2, 4, 3);
scene.add(light);
scene.add(new THREE.AmbientLight(0xffffff, 0.35));

const group = new THREE.Group();
scene.add(group);

const rarityColor = {
  common: 0xcccccc,
  rare: 0x4da3ff,
  special: 0xff8bd6,
  legendary: 0xffd34d,
  mythic: 0x9b7bff,
  limited: 0xff5555,
  celestial: 0x66ffe0,
};

function cardMesh(card, index) {
  const color = rarityColor[card.key] || 0x888888;
  const geo = new THREE.BoxGeometry(1.4, 2, 0.08);
  const mat = new THREE.MeshStandardMaterial({
    color,
    metalness: 0.35,
    roughness: 0.4,
    emissive: color,
    emissiveIntensity: 0.15,
  });
  const mesh = new THREE.Mesh(geo, mat);
  const angle = (index / 8) * Math.PI * 2;
  mesh.position.set(Math.cos(angle) * 2.4, Math.sin(index) * 0.2, Math.sin(angle) * 2.4);
  mesh.rotation.y = angle;
  mesh.userData = card;
  group.add(mesh);
  return mesh;
}

let meshes = [];

function renderCards(cards) {
  meshes.forEach((m) => group.remove(m));
  meshes = cards.slice(0, 12).map((c, i) => cardMesh(c, i));
  if (window.anime) {
    anime({
      targets: group.rotation,
      y: [0, Math.PI * 2],
      duration: 18000,
      easing: "linear",
      loop: true,
    });
  }
}

function animate() {
  requestAnimationFrame(animate);
  group.rotation.y += 0.0025;
  meshes.forEach((m, i) => {
    m.position.y = Math.sin(Date.now() * 0.001 + i) * 0.15;
  });
  renderer.render(scene, camera);
}
animate();

window.addEventListener("resize", () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
}

const initData = tg ? tg.initData : "";
fetch("./api/collection", { headers: { Authorization: "tma " + initData } })
  .then(async (response) => {
    const body = await response.json();
    if (!response.ok) throw new Error(body.error || "Could not load album");
    title.textContent = body.name + " · album";
    meta.textContent = `${body.balance} coins · ${body.claims} catches`;
    badge.textContent = `${body.cards.length} cards`;
    if (!body.cards.length) {
      list.innerHTML = "<li>No cards yet. Catch one in a group.</li>";
      return;
    }
    list.innerHTML = body.cards
      .map(
        (card, idx) =>
          `<li data-idx="${idx}"><strong>${escapeHtml(card.emoji + " " + card.name)}</strong><br>` +
          `${escapeHtml(card.rarity)} · #${card.id}</li>`
      )
      .join("");
    renderCards(body.cards);
    list.querySelectorAll("li").forEach((el) => {
      el.addEventListener("click", () => {
        list.querySelectorAll("li").forEach((n) => n.classList.remove("active"));
        el.classList.add("active");
        const idx = Number(el.dataset.idx);
        const target = meshes[idx % meshes.length];
        if (target && window.anime) {
          anime({
            targets: target.scale,
            x: [1, 1.2, 1],
            y: [1, 1.2, 1],
            duration: 600,
            easing: "easeOutElastic(1, .6)",
          });
        }
      });
    });
  })
  .catch((error) => {
    meta.textContent = error.message;
    meta.classList.add("err");
  });
