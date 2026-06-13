const fs = require('fs');
const path = require('path');

async function runDiagnostics() {
    console.log("=== NVIDIA NIM API Diagnostics ===");
    
    // 1. Read .env file
    const envPath = path.join(__dirname, '.env');
    if (!fs.existsSync(envPath)) {
        console.error("❌ Error: .env file not found!");
        process.exit(1);
    }
    
    const envContent = fs.readFileSync(envPath, 'utf8');
    const match = envContent.match(/NVIDIA_API_KEY\s*=\s*(nvapi-[^\s#\r\n]+)/);
    
    if (!match || !match[1]) {
        console.error("❌ Error: NVIDIA_API_KEY not found or invalid in .env file!");
        process.exit(1);
    }
    
    const apiKey = match[1].trim();
    console.log(`✅ Loaded NVIDIA API Key: ${apiKey.substring(0, 10)}...${apiKey.substring(apiKey.length - 5)}`);
    
    // 2. Fetch Models List
    console.log("\n--- Checking Available LLM Models ---");
    try {
        const response = await fetch("https://integrate.api.nvidia.com/v1/models", {
            headers: {
                "Authorization": `Bearer ${apiKey}`
            }
        });
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status} - ${await response.text()}`);
        }
        
        const modelsJson = await response.json();
        const models = modelsJson.data.map(m => m.id).sort();
        console.log(`✅ Connection Successful! Found ${models.length} models.`);
        
        // Check standard models presence
        const targetModels = [
            "meta/llama-3.1-70b-instruct",
            "meta/llama-3.1-8b-instruct",
            "nvidia/llama-3.1-nemotron-70b-instruct"
        ];
        
        targetModels.forEach(m => {
            if (models.includes(m)) {
                console.log(`  🟢 Available: ${m}`);
            } else {
                console.log(`  🔴 NOT Available: ${m}`);
            }
        });
        
    } catch (err) {
        console.error("❌ Failed to fetch models list:", err.message);
    }
    
    // 3. Test Llama 3.1 70B Generation
    console.log("\n--- Testing Text Generation (meta/llama-3.1-70b-instruct) ---");
    try {
        const response = await fetch("https://integrate.api.nvidia.com/v1/chat/completions", {
            method: "POST",
            headers: {
                "Authorization": `Bearer ${apiKey}`,
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                model: "meta/llama-3.1-70b-instruct",
                messages: [
                    { role: "user", content: "Write a 1-sentence motivational quote about human mind." }
                ],
                max_tokens: 50
            })
        });
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status} - ${await response.text()}`);
        }
        
        const result = await response.json();
        const content = result.choices[0].message.content.trim();
        console.log(`✅ Text Generation Success! Response:\n  "${content}"`);
    } catch (err) {
        console.error("❌ Text generation failed:", err.message);
    }

    // 4. Test FLUX Image Generation
    console.log("\n--- Testing Image Generation (flux-1-dev) ---");
    try {
        const response = await fetch("https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.1-dev", {
            method: "POST",
            headers: {
                "Authorization": `Bearer ${apiKey}`,
                "Content-Type": "application/json",
                "Accept": "application/json"
            },
            body: JSON.stringify({
                prompt: "A beautiful glowing brain in space, neon colors, minimalist 3D render",
                aspect_ratio: "1:1"
            })
        });
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status} - ${await response.text()}`);
        }
        
        const result = await response.json();
        if (result.image || (result.data && result.data[0] && result.data[0].b64_json)) {
            console.log("✅ Image Generation Success! Image data returned successfully.");
        } else {
            console.log("⚠️ Response received but no image data found.", JSON.stringify(result).substring(0, 100));
        }
    } catch (err) {
        console.error("❌ Image generation failed:", err.message);
    }
    // 5. Test OpenRouter if present
    const openRouterMatch = envContent.match(/OPENROUTER_API_KEY\s*=\s*([^\s#\r\n]+)/);
    if (openRouterMatch && openRouterMatch[1]) {
        const orKey = openRouterMatch[1].trim();
        console.log(`\n--- Testing OpenRouter Generation (meta-llama/llama-3.1-8b-instruct:free) ---`);
        try {
            const response = await fetch("https://openrouter.ai/api/v1/chat/completions", {
                method: "POST",
                headers: {
                    "Authorization": `Bearer ${orKey}`,
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    model: "meta-llama/llama-3.1-8b-instruct:free",
                    messages: [
                        { role: "user", content: "Hi! Output the word 'OpenRouter OK'." }
                    ]
                })
            });
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status} - ${await response.text()}`);
            }
            
            const result = await response.json();
            const content = result.choices[0].message.content.trim();
            console.log(`✅ OpenRouter Success! Response: "${content}"`);
        } catch (err) {
            console.error("❌ OpenRouter test failed:", err.message);
        }
    } else {
        console.log("\nℹ️ OpenRouter test skipped (OPENROUTER_API_KEY not found in .env)");
    }
    
    console.log("\n=== Diagnostics Completed ===");
}

runDiagnostics();
