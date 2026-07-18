const BASE_URL = "/apps/usgs-water-stage-qc";

let state;
let runId;
let workers;


function showError(message) {
    document.querySelector(".loading-container").style.display = "none";
    document.querySelector(".error-message-container").style.display = "block";
    document.querySelector(".error-message").textContent = message;
}

function returnToPreviousPage() {
    window.location.href = `/apps/usgs-water-stage-qc`;
    return;
}

async function runFloodAlert() {
    state = document.getElementById("state-name").value.toLowerCase();
    runId = document.getElementById("run-id").value;
    workers = document.getElementById("workers").value;

    const csrf = document.getElementById("csrf-token").value;
    
    try {
        const url = `/apps/usgs-water-stage-qc/do_run_flood_alert/`;
        const body = new FormData();
        body.append("state", state);
        body.append("run_id", runId);
        body.append("workers", workers);
        const res = await fetch(url, { 
            method: "POST", 
            headers: { "X-CSRFToken": csrf }, 
            body });
        const data = await res.json();

        if (data.status === "success") {
            window.location.href = `/apps/usgs-water-stage-qc/flood-alert/results/${state}/${runId}/`;
        } else {
            showError("Flood alert generation failed.");
        }
    } catch (err) {
        showError("Flood alert generation failed.");
        console.error(err);
    }
}
console.log("Flood alert generating script loaded");
document.addEventListener("DOMContentLoaded", runFloodAlert);