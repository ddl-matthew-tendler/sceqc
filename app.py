# app.py
import os
import logging
from urllib.parse import urljoin

import requests
from flask import Flask, render_template, request, Response, jsonify
import queue
import json

from model_registration import register_model_handler, assist_governance_handler

app = Flask(__name__, static_url_path='/static')
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB limit

logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s:%(name)s:%(message)s'
)
logger = logging.getLogger(__name__)
logging.getLogger('werkzeug').setLevel(logging.INFO)
logging.getLogger('urllib3.connectionpool').setLevel(logging.WARNING)

DOMINO_DOMAIN = os.environ.get("DOMINO_DOMAIN", "govqcexploratory.domino.tech")
DOMINO_API_KEY = os.environ.get("DOMINO_USER_API_KEY", "")
DOMINO_PROJECT_ID = os.environ.get("DOMINO_PROJECT_ID", "")

logger.info(f"DOMINO_DOMAIN: {DOMINO_DOMAIN}")
logger.info(f"DOMINO_API_KEY: {'***' if DOMINO_API_KEY else 'NOT SET'}")
logger.info(f"DOMINO_PROJECT_ID: {DOMINO_PROJECT_ID}")

progress_queues = {}


@app.route("/_stcore/health")
def health():
    return "", 200


@app.route("/_stcore/host-config")
def host_config():
    return "", 200


@app.route("/register-progress/<request_id>")
def register_progress(request_id):
    """SSE endpoint for progress updates."""
    def generate():
        q = queue.Queue()
        progress_queues[request_id] = q
        try:
            while True:
                data = q.get()
                if data.get('done'):
                    break
                yield f"data: {json.dumps(data)}\n\n"
        finally:
            if request_id in progress_queues:
                del progress_queues[request_id]
    
    return Response(generate(), mimetype='text/event-stream')


@app.route("/proxy/<path:path>", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
def proxy_request(path):
    """Proxy requests to upstream services."""
    logger.info(f"Proxy request: {request.method} {path}")
    
    if request.method == "OPTIONS":
        return "", 204
    
    target_base = request.args.get('target')
    if not target_base:
        return jsonify({"error": "Missing target URL. Use ?target=https://api.example.com"}), 400
    
    upstream_url = urljoin(target_base.rstrip("/") + "/", path)
    
    skip_headers = {"host", "content-length", "transfer-encoding", "connection", "keep-alive", "authorization"}
    forward_headers = {k: v for k, v in request.headers if k.lower() not in skip_headers}
    upstream_params = {k: v for k, v in request.args.items() if k != 'target'}
    
    logger.info(f"Making upstream request: {request.method} {upstream_url}")
    
    try:
        resp = requests.request(
            method=request.method,
            url=upstream_url,
            params=upstream_params,
            data=request.get_data(),
            headers=forward_headers,
            timeout=30,
            stream=True
        )
        
        logger.info(f"Upstream response: {resp.status_code}")
        
        hop_by_hop = {"content-encoding", "transfer-encoding", "connection", "keep-alive"}
        response_headers = [(k, v) for k, v in resp.headers.items() if k.lower() not in hop_by_hop]
        
        if resp.status_code >= 400:
            try:
                content = resp.content
                logger.error(f"Upstream error response: {content[:1000].decode('utf-8', errors='ignore')}")
                return Response(content, status=resp.status_code, headers=response_headers)
            except Exception as e:
                logger.error(f"Error reading response content: {e}")
        
        return Response(
            resp.iter_content(chunk_size=8192),
            status=resp.status_code,
            headers=response_headers,
            direct_passthrough=True
        )
        
    except requests.RequestException as e:
        logger.error(f"Proxy request failed: {e}")
        return jsonify({"error": f"Proxy request failed: {e}"}), 502
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return jsonify({"error": f"Unexpected error: {e}"}), 500


@app.route("/register-external-model", methods=["POST"])
def register_external_model():
    """Register an external model with Domino using MLflow."""
    return register_model_handler(request, progress_queues)


@app.route("/assist-governance", methods=["POST"])
def assist_governance():
    """Call gateway LLM to assist with populating governance fields."""
    return assist_governance_handler(request)


@app.route("/api/policies", methods=["GET"])
def get_policies():
    """Fetch all governance policies from the Domino API."""
    try:
        url = f"https://{DOMINO_DOMAIN}/api/governance/v1/policy-overviews"
        headers = {
            'X-Domino-Api-Key': DOMINO_API_KEY,
            'accept': 'application/json'
        }

        logger.info(f"Fetching policies from: {url}")
        response = requests.get(url, headers=headers, timeout=30)

        if not response.ok:
            logger.error(f"Failed to fetch policies: {response.status_code}")
            return jsonify({"error": f"Failed to fetch policies: {response.status_code}"}), response.status_code

        data = response.json()
        logger.info(f"Successfully fetched {len(data.get('data', []))} policies")
        return jsonify(data)

    except requests.RequestException as e:
        logger.error(f"Error fetching policies: {e}")
        return jsonify({"error": f"Error fetching policies: {str(e)}"}), 500
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return jsonify({"error": f"Unexpected error: {str(e)}"}), 500


@app.route("/api/bundles", methods=["GET"])
def get_bundles():
    """Fetch all governance bundles from the Domino API."""
    try:
        url = f"https://{DOMINO_DOMAIN}/api/governance/v1/bundles"
        headers = {
            'X-Domino-Api-Key': DOMINO_API_KEY,
            'accept': 'application/json'
        }

        logger.info(f"Fetching bundles from: {url}")
        response = requests.get(url, headers=headers, timeout=30)

        if not response.ok:
            logger.error(f"Failed to fetch bundles: {response.status_code}")
            return jsonify({"error": f"Failed to fetch bundles: {response.status_code}"}), response.status_code

        data = response.json()
        logger.info(f"Successfully fetched {len(data.get('data', []))} bundles")
        return jsonify(data)

    except requests.RequestException as e:
        logger.error(f"Error fetching bundles: {e}")
        return jsonify({"error": f"Error fetching bundles: {str(e)}"}), 500
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return jsonify({"error": f"Unexpected error: {str(e)}"}), 500


@app.route("/api/bundles/<bundle_id>/stages/<stage_id>/assignee", methods=["PUT"])
def update_stage_assignee(bundle_id, stage_id):
    """Update the assignee for a specific stage in a bundle."""
    try:
        data = request.get_json() or {}
        assignee_id = data.get('assigneeId')
        assignee_name = data.get('assigneeName')

        # Build the API URL - using PATCH to /bundles/{id}/stages/{id} (not /assignee)
        url = f"https://{DOMINO_DOMAIN}/api/governance/v1/bundles/{bundle_id}/stages/{stage_id}"
        headers = {
            'X-Domino-Api-Key': DOMINO_API_KEY,
            'accept': 'application/json',
            'Content-Type': 'application/json'
        }

        # Payload format: {"assignee": {"id": "...", "name": "..."}} or {"assignee": null}
        if assignee_id and assignee_name:
            payload = {
                "assignee": {
                    "id": assignee_id,
                    "name": assignee_name
                }
            }
        else:
            payload = {"assignee": None}

        logger.info(f"Updating assignee for bundle {bundle_id}, stage {stage_id} to: {payload}")

        # Use PATCH instead of PUT
        response = requests.patch(url, headers=headers, json=payload, timeout=30)

        if not response.ok:
            error_text = response.text
            logger.error(f"Failed to update assignee: {response.status_code}, Response: {error_text}")
            return jsonify({
                "error": f"Failed to update assignee: {response.status_code}",
                "details": error_text
            }), response.status_code

        logger.info(f"Successfully updated assignee for bundle {bundle_id}, stage {stage_id}")
        return jsonify(response.json() if response.content else {"success": True})

    except requests.RequestException as e:
        logger.error(f"Error updating assignee: {e}")
        return jsonify({"error": f"Error updating assignee: {str(e)}"}), 500
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return jsonify({"error": f"Unexpected error: {str(e)}"}), 500


@app.route("/api/users/test", methods=["GET"])
def test_users_route():
    """Simple test endpoint to verify routing works."""
    return jsonify({"message": "Users route is accessible", "test": True})


@app.route("/api/users", methods=["GET"])
def get_users():
    """Fetch project collaborators from the Domino API for assignee dropdowns."""
    try:
        logger.info("=== GET /api/users endpoint called ===")

        if not DOMINO_PROJECT_ID:
            logger.error("DOMINO_PROJECT_ID not set")
            return jsonify({"error": "Project ID not configured"}), 500

        url = f"https://{DOMINO_DOMAIN}/v4/projects/{DOMINO_PROJECT_ID}/collaborators"
        headers = {
            'X-Domino-Api-Key': DOMINO_API_KEY,
            'accept': 'application/json'
        }

        # Get only users (not organizations)
        params = {
            'getUsers': True
        }

        logger.info(f"Fetching project collaborators from: {url}")
        logger.info(f"Request params: {params}")
        logger.info(f"API Key present: {bool(DOMINO_API_KEY)}")

        response = requests.get(url, headers=headers, params=params, timeout=30)

        logger.info(f"Response status code: {response.status_code}")
        logger.info(f"Response headers: {dict(response.headers)}")

        if not response.ok:
            logger.error(f"Failed to fetch project collaborators: {response.status_code}")
            logger.error(f"Response body: {response.text}")
            return jsonify({"error": f"Failed to fetch project collaborators: {response.status_code}"}), response.status_code

        collaborators = response.json()
        logger.info(f"Successfully fetched {len(collaborators)} project collaborators")
        logger.info(f"Raw collaborators data: {collaborators}")

        # Transform the response to match the expected format
        # The collaborators endpoint returns Person objects with fields like: id, userName, firstName, lastName, etc.
        users = []
        for person in collaborators:
            user = {
                'id': person.get('id'),
                'username': person.get('userName'),
                'fullName': f"{person.get('firstName', '')} {person.get('lastName', '')}".strip() or person.get('userName')
            }
            users.append(user)

        result = {"users": users}
        logger.info(f"Returning transformed users: {result}")
        return jsonify(result)

    except requests.RequestException as e:
        logger.error(f"Error fetching project collaborators: {e}", exc_info=True)
        return jsonify({"error": f"Error fetching project collaborators: {str(e)}"}), 500
    except Exception as e:
        logger.error(f"Unexpected error in get_users: {e}", exc_info=True)
        return jsonify({"error": f"Unexpected error: {str(e)}"}), 500


@app.route("/api/debug/info", methods=["GET"])
def get_debug_info():
    """Get debugging information about the app configuration and recent logs."""
    try:
        debug_info = {
            "config": {
                "DOMINO_DOMAIN": DOMINO_DOMAIN,
                "DOMINO_PROJECT_ID": DOMINO_PROJECT_ID,
                "API_KEY_SET": bool(DOMINO_API_KEY),
                "API_KEY_PREFIX": DOMINO_API_KEY[:10] + "..." if DOMINO_API_KEY else "NOT SET"
            },
            "endpoints": {
                "policies": f"https://{DOMINO_DOMAIN}/api/governance/v1/policy-overviews",
                "bundles": f"https://{DOMINO_DOMAIN}/api/governance/v1/bundles",
                "users": f"https://{DOMINO_DOMAIN}/v4/projects/{DOMINO_PROJECT_ID}/collaborators",
                "update_assignee": f"https://{DOMINO_DOMAIN}/api/governance/v1/bundles/{{bundleId}}/stages/{{stageId}}"
            },
            "timestamp": os.popen('date').read().strip()
        }
        return jsonify(debug_info)
    except Exception as e:
        logger.error(f"Error getting debug info: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/debug/test-connection", methods=["POST"])
def test_connection():
    """Test connection to a specific Domino API endpoint."""
    try:
        data = request.get_json() or {}
        endpoint = data.get('endpoint', 'policies')

        if endpoint == 'policies':
            url = f"https://{DOMINO_DOMAIN}/api/governance/v1/policy-overviews"
        elif endpoint == 'bundles':
            url = f"https://{DOMINO_DOMAIN}/api/governance/v1/bundles"
        elif endpoint == 'users':
            url = f"https://{DOMINO_DOMAIN}/v4/projects/{DOMINO_PROJECT_ID}/collaborators?getUsers=true"
        else:
            return jsonify({"error": "Invalid endpoint"}), 400

        headers = {
            'X-Domino-Api-Key': DOMINO_API_KEY,
            'accept': 'application/json'
        }

        logger.info(f"Testing connection to: {url}")
        response = requests.get(url, headers=headers, timeout=10)

        result = {
            "url": url,
            "status_code": response.status_code,
            "ok": response.ok,
            "headers": dict(response.headers),
            "response_preview": response.text[:500] if response.text else None
        }

        logger.info(f"Connection test result: {response.status_code}")
        return jsonify(result)

    except Exception as e:
        logger.error(f"Connection test failed: {e}")
        return jsonify({"error": str(e), "type": type(e).__name__}), 500


def safe_domino_config():
    """Return sanitized Domino configuration for templates."""
    return {
        "PROJECT_ID": DOMINO_PROJECT_ID,
        "RUN_HOST_PATH": os.environ.get("DOMINO_RUN_HOST_PATH", ""),
        "API_BASE": DOMINO_DOMAIN,
        "API_KEY": DOMINO_API_KEY,
    }


@app.route("/")
def home():
    return render_template("index.html", DOMINO=safe_domino_config())


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8888))
    logger.info(f"Starting Flask app on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)