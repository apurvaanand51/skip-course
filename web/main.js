// --------------------
// Elements
// --------------------

const csrfInput = document.getElementById("csrf");
const uuInput = document.getElementById("uu");
const cauthInput = document.getElementById("cauth");

const jsonOutput = document.getElementById("json-output");

const generateBtn = document.getElementById("generate");
const copyBtn = document.getElementById("copy");
const saveBtn = document.getElementById("save");

const urlInput = document.getElementById("course-url");
const slugOutput = document.getElementById("slug-output");

const extractBtn = document.getElementById("extract");
const copySlugBtn = document.getElementById("copy-slug");



// --------------------
// Helper
// --------------------

async function copyText(text, button, originalText) {
    if (!text.trim()) return;

    try {
        await navigator.clipboard.writeText(text);

        button.textContent = "Copied ✓";

        setTimeout(() => {
            button.textContent = originalText;
        }, 1800);

    } catch (err) {
        alert("Unable to copy.");
    }
}

// --------------------
// JSON Generator
// --------------------

generateBtn.addEventListener("click", () => {

    const csrf = csrfInput.value.trim();
    const uu = uuInput.value.trim();
    const cauth = cauthInput.value.trim();

    if (!csrf || !uu || !cauth) {
        alert("Please fill in all three cookie values.");
        return;
    }

    const config = {
        cookies: {
            CAUTH: cauth,
            "CSRF3-Token": csrf,
            "__204u": uu
        }
    };

    jsonOutput.textContent = JSON.stringify(config, null, 4);

});

// --------------------
// Copy JSON
// --------------------

copyBtn.addEventListener("click", () => {

    copyText(
        jsonOutput.textContent,
        copyBtn,
        "Copy JSON"
    );

});

// --------------------
// Slug Extraction
// --------------------

function extractSlug() {

    const url = urlInput.value.trim();

    if (!url) {
        slugOutput.textContent = "";
        alert("Please enter a Coursera course URL.");
        return;
    }

    try {

        const parsed = new URL(url);

        const parts = parsed.pathname
            .split("/")
            .filter(Boolean);

        const learnIndex = parts.indexOf("learn");

        if (
            learnIndex !== -1 &&
            learnIndex + 1 < parts.length
        ) {

            slugOutput.textContent = parts[learnIndex + 1];

        } else {

            slugOutput.textContent =
                "Invalid Coursera course URL.";

        }

    } catch {

        slugOutput.textContent = "Invalid URL.";

    }

}

extractBtn.addEventListener("click", extractSlug);

// --------------------
// Press Enter to Extract
// --------------------

urlInput.addEventListener("keydown", (e) => {

    if (e.key === "Enter") {
        extractSlug();
    }

});

// --------------------
// Copy Slug
// --------------------

copySlugBtn.addEventListener("click", () => {

    const slug = slugOutput.textContent.trim();

    if (
        !slug ||
        slug === "Invalid URL." ||
        slug === "Invalid Coursera course URL."
    ) {
        alert("Extract a valid course slug first.");
        return;
    }

    copyText(
        slug,
        copySlugBtn,
        "Copy Slug"
    );

});

// --------------------
// Auto Select Output
// --------------------

jsonOutput.addEventListener("click", () => {

    const range = document.createRange();
    range.selectNodeContents(jsonOutput);

    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);

});

slugOutput.addEventListener("click", () => {

    const range = document.createRange();
    range.selectNodeContents(slugOutput);

    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);

});

saveBtn.addEventListener("click", () => {

    const csrf = csrfInput.value.trim();
    const uu = uuInput.value.trim();
    const cauth = cauthInput.value.trim();

    if (!csrf || !uu || !cauth) {
        alert("Please fill in all three cookie values.");
        return;
    }

    const config = {
        cookies: {
            CAUTH: cauth,
            "CSRF3-Token": csrf,
            "__204u": uu
        }
    };

    const blob = new Blob(
        [JSON.stringify(config, null, 4)],
        { type: "application/json" }
    );

    const url = URL.createObjectURL(blob);

    const a = document.createElement("a");
    a.href = url;
    a.download = "config.json";

    document.body.appendChild(a);
    a.click();
    a.remove();

    URL.revokeObjectURL(url);

});