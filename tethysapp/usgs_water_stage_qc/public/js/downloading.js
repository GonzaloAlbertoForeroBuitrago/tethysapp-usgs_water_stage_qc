const BASE_URL = "/apps/usgs-water-stage-qc";

let state;
let gageId;


function showError(message) {
    document.querySelector(".download-container").style.display = "none";
    document.querySelector(".error-message-container").style.display = "block";
    document.querySelector(".error-message").textContent = message;
}

function returnToPreviousPage() {
    if (gageId) {
        window.location.href = `/apps/usgs-water-stage-qc/basin/${state}`;
        return;
    } else {
        window.location.href = `/apps/usgs-water-stage-qc`;
        return;
    }
}

async function downloadData() {
    state = document.getElementById("state-name").value.toLowerCase();
    gageId = document.getElementById("gage-id").value.trim();
    const csrf = document.getElementById("csrf-token").value;

    try {
        const url = gageId
        ? `/apps/usgs-water-stage-qc/do_download_stage/${state}/${gageId}/`
        : `/apps/usgs-water-stage-qc/do_download_basin/${state}/`;

        const res = await fetch(url, { method: "POST", headers: { "X-CSRFToken": csrf } });
        const data = await res.json();

        if (data.status === "success") {
        window.location.href = gageId
            ? `/apps/usgs-water-stage-qc/basin/${state}/${gageId}/`
            : `/apps/usgs-water-stage-qc/basin/${state}/`;
        } else {
            if (res.status === 404) {
                if (gageId) {
                showError('No data could be found for the specified gage ID. Try again later, as this data may not yet be available in the system.');
                }
                else {
                showError('No basin data could be found for the specified state.');
                }        
            }
        }
    } catch (err) {
        showError("Download failed.");
        console.error(err);
    }
}
document.addEventListener("DOMContentLoaded", downloadData);