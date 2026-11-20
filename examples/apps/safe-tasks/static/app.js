// Tasks are rendered with textContent, never innerHTML, so a title cannot inject markup.
const form = document.getElementById("add");
const list = document.getElementById("tasks");

async function load(owner) {
  const res = await fetch(`/tasks?owner=${encodeURIComponent(owner)}`);
  const { tasks } = await res.json();
  list.replaceChildren(...tasks.map((title) => {
    const item = document.createElement("li");
    item.textContent = title;
    return item;
  }));
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const owner = document.getElementById("owner").value;
  const title = document.getElementById("title");
  await fetch("/tasks", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ owner, title: title.value }),
  });
  title.value = "";
  load(owner);
});
