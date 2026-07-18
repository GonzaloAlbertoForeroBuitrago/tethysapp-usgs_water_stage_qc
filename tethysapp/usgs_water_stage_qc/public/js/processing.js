const BASE_URL = "/apps/usgs-water-stage-qc/";

const PROCESS_URLS = {
    'basin_download': BASE_URL + "do_download_basin/",
    'zarr_download': BASE_URL + "do_download_zarr/",
    'flood_alert': BASE_URL + "do_run_flood_alert/"
}

const DOWNLOAD_PROCESS_BASE_URL = BASE_URL + "basin/";
const FLOOD_ALERT_PROCESS_BASE_URL = BASE_URL + "flood-alert/";
// const FLOOD_ALERT_RESULT_BASE_UR

const DOWNLOAD_PROCESS_PREVIOUS_BASE_URL = BASE_URL + "/basin/";

let csrfToken;
let state;
let gageId;
let runId;
let workers;
let processType;

async function runProcess() {
    let url;
    if (processType === "basin_download") {
        url = PROCESS_URLS.basin_download + state + "/";
    } else if (processType === "zarr_download") {
        url = PROCESS_URLS.zarr_download + state + "/" + gageId + "/";
     } else if (processType === "flood_alert") {
        url = PROCESS_URLS.flood_alert;
    }

    try {
        let res;
        let data;

        if (processType === "flood_alert") {
            const body = new FormData();
            body.append("state", state);
            body.append("run_id", runId);
            body.append("workers", workers);
            res = await fetch(url, { method: "POST", headers: { "X-CSRFToken": csrfToken }, body });
            data = await res.json();
        } else {
            res = await fetch(url, { method: "POST", headers: { "X-CSRFToken": csrfToken } });
            data = await res.json();
        }
        

        if (data.status === "success") {
            let resultUrl;
            if (processType === "basin_download") {
                window.location.href = DOWNLOAD_PROCESS_BASE_URL + state + "/";
            } else if (processType === "zarr_download") {
                window.location.href = DOWNLOAD_PROCESS_BASE_URL + state + "/" + gageId + "/";
            } else if (processType === "flood_alert") {
                resultUrl = BASE_URL + "flood-alert/run/";
                const form = document.createElement("form");
                form.method = "POST";
                form.action = resultUrl;

                const csrfInput = document.createElement("input");
                csrfInput.type = "hidden";
                csrfInput.name = "csrfmiddlewaretoken";
                csrfInput.value = csrfToken;
                form.appendChild(csrfInput);

                const runIdInput = document.createElement("input");
                runIdInput.type = "hidden";
                runIdInput.name = "run_id";
                runIdInput.value = runId;
                form.appendChild(runIdInput);

                const stateInput = document.createElement("input");
                stateInput.type = "hidden";
                stateInput.name = "state";
                stateInput.value = state;
                form.appendChild(stateInput);

                const workersInput = document.createElement("input");
                workersInput.type = "hidden";
                workersInput.name = "workers";
                workersInput.value = workers;
                form.appendChild(workersInput);

                document.body.appendChild(form);
                form.submit();
                return;
            }
        } else {
            if (res.status === 404) {
                if (processType === "basin_download") {
                    showError('No basin data could be found for the specified state.');
                } else if (processType === "zarr_download") {
                    showError('No data could be found for the specified gage ID. Try again later, as this data may not yet be available in the system.');
                }
            }
        }
    } catch (err) {
        if (processType === "basin_download" || processType === "zarr_download") {
            showError("Download failed");
        } else {
            showError("Flood alert generation failed.");
        }
    }
}

function loadProcessData() {
    const processData = JSON.parse(
        document.getElementById("processing-data").textContent
    );
    csrfToken = processData.csrfToken;
    state = processData.state;
    gageId = processData.gageId;
    runId = processData.runId;
    workers = processData.workers;
    processType = processData.processType;
}

function showError(message) {
    document.querySelector(".process-container").style.display = "none";
    document.querySelector(".error-message-container").style.display = "block";
    document.querySelector(".error-message").textContent = message;
}

function returnToPreviousPage() {
    if (processType === "basin_download") {
        window.location.href = DOWNLOAD_PROCESS_BASE_URL;
    } else if (processType === "zarr_download") {
        window.location.href = DOWNLOAD_PROCESS_BASE_URL + state + "/";
    } else if (processType === "flood_alert") {
        window.location.href = FLOOD_ALERT_PROCESS_BASE_URL;
    }
}
document.addEventListener("DOMContentLoaded", () => {
    loadProcessData();
    runProcess();
});