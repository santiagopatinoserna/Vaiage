document.addEventListener('DOMContentLoaded', function() {
    // Initialize map
    const mapContainer = document.getElementById('map');
    if (!mapContainer) {
        console.error('Map container not found!');
        return;
    }

    let map;
    let markersLayer = L.layerGroup();  // Initialize markers layer
    try {
        map = L.map('map').setView([20, 0], 2); // Default to World view
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap> contributors',
            maxZoom: 19
        }).addTo(map);
        markersLayer.addTo(map);  // Add markers layer to map
        console.log('Map initialized successfully');
    } catch (error) {
        console.error('Error initializing map:', error);
    }

    // Cache DOM elements
    const chatForm = document.getElementById('chat-form');
    const userInput = document.getElementById('user-input');
    const chatContainer = document.getElementById('chat-container');
    const itineraryContainer = document.getElementById('itinerary-container'); ///////////
    const recommendationsContainer = document.getElementById('recommendations-container');
    const paginatedRecommendationsContainer = document.getElementById('paginated-recommendations-container');
    const attractionContentArea = document.getElementById('attraction-content-area');
    const recommendationsPaginationControls = document.getElementById('recommendations-pagination-controls');
    const prevAttractionBtn = document.getElementById('prev-attraction-btn');
    const nextAttractionBtn = document.getElementById('next-attraction-btn');
    const attractionPageInfo = document.getElementById('attraction-page-info');
    const confirmAllSelectionsFooter = document.getElementById('confirm-all-selections-footer');
    const confirmSelectedAttractionsBtn = document.getElementById('confirm-selected-attractions-btn');
    const loadingSpinner = document.getElementById('loading-spinner');
    const resetBtn = document.getElementById('reset-btn');
    const stepNav = document.getElementById('step-nav');
    const missingFieldsContainer = document.getElementById('missing-fields');
    const selectedAttractionsList = document.getElementById('selected-attractions');

    // Initialize marker layers
    let selectedMarkersLayer = L.layerGroup().addTo(map);
    let currentAttractions = [];
    let selectedAttractions = [];
    let currentRecommendationPage = 0;

    // Auto-scroll for popular attractions
    function initAutoScroll() {
        const scrollContainer = document.querySelector('.scroll-container');
        if (scrollContainer) {
            console.log('Scroll container found, initializing auto-scroll');
            // Duplicate content for seamless looping
            scrollContainer.innerHTML += scrollContainer.innerHTML;

            let scrollSpeed = 1; // Pixels per frame
            let animationFrame;
            let isPaused = false;

            function autoScroll() {
                if (!isPaused) {
                    scrollContainer.scrollTop += scrollSpeed;
                    if (scrollContainer.scrollTop >= scrollContainer.scrollHeight / 2) {
                        scrollContainer.scrollTop = 0;
                    }
                }
                animationFrame = requestAnimationFrame(autoScroll);
            }

            // Pause on hover
            scrollContainer.addEventListener('mouseenter', () => {
                isPaused = true;
            });

            // Resume on mouse leave
            scrollContainer.addEventListener('mouseleave', () => {
                isPaused = false;
            });

            // Start scrolling
            autoScroll();
        } else {
            console.log('Scroll container not found');
        }
    }

    // Use MutationObserver to detect .scroll-container dynamically
    const observer = new MutationObserver((mutations) => {
        if (document.querySelector('.scroll-container')) {
            initAutoScroll();
            observer.disconnect(); // Stop observing once found
        }
    });
    observer.observe(document.body, { childList: true, subtree: true });

    // Update step navigation highlighting
    function updateStepNav(step) {
        if (!stepNav) {
            console.log('Step navigation not found, skipping update');
            return;
        }
        const links = stepNav.querySelectorAll('.nav-link');
        links.forEach(link => {
            if (link.dataset.step === step) {
                link.classList.add('active');
            } else {
                link.classList.remove('active');
            }
        });
    }
    // Show missing fields list
    function showMissingFields(fields) {
        if (!missingFieldsContainer) {
            console.log('Missing fields container not found, skipping update');
            return;
        }
        missingFieldsContainer.innerHTML = '<strong>Additional information needed: </strong>' +
            fields.map(f => `<span class="badge bg-warning text-dark me-1">${f}</span>`).join('');
        missingFieldsContainer.classList.remove('d-none');
    }
    
    // Hide missing fields alert
    function hideMissingFields() {
        missingFieldsContainer.classList.add('d-none');
    }
    
    // Store markers for later reference
    let mapMarkers = [];
    
    // Store state
    let state = {
        step: 'chat',
        userInfo: {},
        attractions: [],
        selectedAttractions: [],
        itinerary: null,
        budget: null,
        ai_recommendation_generated: false,
        user_input_processed: false,
        session_id: null,
        rental_post: null
    };

    // Handle form submission
    chatForm.addEventListener('submit', function(e) {
        e.preventDefault();
        const message = userInput.value.trim();
        
        if (message) {
            // Add user message to chat
            addChatMessage(message, 'user');
            
            // Clear input
            userInput.value = '';
            
            // Send to backend
            processUserInput(message);
        }
    });
    
    // Reset button
    resetBtn.addEventListener('click', function() {
        resetConversation();
    });
    
    // Add a message to the chat container
    function addChatMessage(message, role) {
        const messageDiv = document.createElement('div');
        messageDiv.className = `chat-message ${role}`;
        
        const messageContent = document.createElement('div');
        messageContent.className = 'message-content';
        
        // Use marked to render Markdown content
        messageContent.innerHTML = marked.parse(message);
        
        messageDiv.appendChild(messageContent);
        chatContainer.appendChild(messageDiv);
        
        // Scroll to bottom
        chatContainer.scrollTop = chatContainer.scrollHeight;
    }
    
    // Process user input by sending to backend
    function processUserInput(message) {
        // Show loading spinner
        loadingSpinner.classList.remove('d-none');
        
        // Create a new message container for the assistant's response
        const messageDiv = document.createElement('div');
        messageDiv.className = 'chat-message assistant';
        const messageContent = document.createElement('div');
        messageContent.className = 'message-content';
        messageDiv.appendChild(messageContent);
        chatContainer.appendChild(messageDiv);
        
        // Create EventSource for streaming
        const params = new URLSearchParams({
            step: state.step,
            user_input: message
        });
        
        // Only add session_id if it exists and is not null
        if (state.session_id) {
            params.append('session_id', state.session_id);
        }
        
        // Add selected attractions if in recommend step
        if (state.step === 'recommend' && state.selectedAttractions.length > 0) {
            params.append('selected_attraction_ids', JSON.stringify(state.selectedAttractions.map(a => a.id)));
        }
        
        // Add state flags if they exist
        if (state.ai_recommendation_generated !== undefined) {
            params.append('ai_recommendation_generated', state.ai_recommendation_generated.toString());
        }
        if (state.user_input_processed !== undefined) {
            params.append('user_input_processed', state.user_input_processed.toString());
        }
        
        console.log('[DEBUG] Sending request with params:', params.toString());
        console.log('[DEBUG] Current state:', state);
        
        const eventSource = new EventSource(`/api/stream?${params.toString()}`);
        
        let fullResponse = '';
        
        eventSource.onmessage = function(event) {
            const data = JSON.parse(event.data);
            console.log('[DEBUG] Received data:', data);
            
            if (data.type === 'chunk') {
                fullResponse += data.content;
                messageContent.innerHTML = marked.parse(fullResponse);
                chatContainer.scrollTop = chatContainer.scrollHeight;
            } else if (data.type === 'complete') {
                eventSource.close();
                loadingSpinner.classList.add('d-none');
                
                console.log('[DEBUG] processUserInput - Received COMPLETE message with data:', JSON.parse(JSON.stringify(data)));

                if (data.attractions) {
                    console.log('[DEBUG] processUserInput - data.attractions received:', JSON.parse(JSON.stringify(data.attractions)));
                }
                if (data.map_data) {
                    console.log('[DEBUG] processUserInput - data.map_data received:', JSON.parse(JSON.stringify(data.map_data)));
                }
            
                const prevStep = state.step;
                state.step = data.next_step || state.step;
                if (data.next_step) {
                    updateStepNav(data.next_step);
                }
                
                // Store session_id if provided
                if (data.session_id) {
                    state.session_id = data.session_id;
                    console.log('[DEBUG] Updated session_id:', state.session_id);
                }
                
                // Display or hide missing fields
                if (data.missing_fields && data.missing_fields.length > 0) {
                    showMissingFields(data.missing_fields);
                } else {
                    hideMissingFields();
                }
                
                // Update state from response
                if (data.state) {
                    console.log('[DEBUG] Updating state with:', data.state);
                    if (data.state.user_info) state.userInfo = data.state.user_info;
                    if (data.state.attractions) state.attractions = data.state.attractions;
                    if (data.state.selected_attractions) state.selectedAttractions = data.state.selected_attractions;
                    if (data.state.itinerary) state.itinerary = data.state.itinerary;
                    if (data.state.budget) state.budget = data.state.budget;
                    if (data.state.ai_recommendation_generated !== undefined) {
                        state.ai_recommendation_generated = Boolean(data.state.ai_recommendation_generated);
                        console.log('[DEBUG] Updated ai_recommendation_generated:', state.ai_recommendation_generated);
                    }
                    if (data.state.user_input_processed !== undefined) {
                        state.user_input_processed = Boolean(data.state.user_input_processed);
                        console.log('[DEBUG] Updated user_input_processed:', state.user_input_processed);
                    }
                }
                
                // Update UI components
                if (data.attractions) updateAttractions(data.attractions);
                if (data.map_data) updateMap(data.map_data);
                if (data.itinerary) updateItinerary(data.itinerary);
                if (data.budget) updateBudget(data.budget);
                if (data.response) updateConfirmation(data.response);
                
                // If we have route data, draw it on the map
                if (data.optimal_route) {
                    drawRoute(data.optimal_route);
                }

                console.log('[DEBUG] Final state:', state);
            } else if (data.type === 'error') {
                eventSource.close();
                loadingSpinner.classList.add('d-none');
                messageContent.innerHTML = 'Sorry, there was an error processing your request. Please try again.';
                console.error('Error:', data.error);
            }
        };
        
        eventSource.onerror = function(error) {
            console.error('EventSource failed:', error);
            eventSource.close();
            loadingSpinner.classList.add('d-none');
            messageContent.innerHTML = 'Sorry, there was an error processing your request. Please try again.';
        };
    }
    
    // Update map with new data
    function updateMap(data) {
        if (!map) return;
        markersLayer.clearLayers();

        if (!data || !Array.isArray(data)) {
            console.error('Invalid map data:', data);
            return;
        }

        let bounds = L.latLngBounds([]);  // Initialize empty bounds
        let validMarkers = 0;

        data.forEach(attraction => {
            if (!attraction || !attraction.location || 
                typeof attraction.location.lat !== 'number' || 
                typeof attraction.location.lng !== 'number') {
                console.error('Invalid attraction data:', attraction);
                return;
            }

            const marker = L.marker([attraction.location.lat, attraction.location.lng])
                .bindPopup(`
                    <h3>${attraction.name || 'Unknown'}</h3>
                    <p>${attraction.address || 'No address available'}</p>
                    <p>Rating: ${attraction.rating || 'No rating'}</p>
                    <button onclick="selectAttraction('${attraction.id || ''}')">Select</button>
                `);
            markersLayer.addLayer(marker);
            bounds.extend([attraction.location.lat, attraction.location.lng]);
            validMarkers++;
        });

        // Only fit bounds if we have valid markers
        if (validMarkers > 0) {
            try {
                map.fitBounds(bounds.pad(0.1));
            } catch (error) {
                console.error('Error fitting map bounds:', error);
                // Fallback to default view if bounds fitting fails
                map.setView([48.8566, 2.3522], 13);
            }
        } else {
            // If no valid markers, reset to default view
            map.setView([48.8566, 2.3522], 13);
        }
    }
    
    // Update attractions display (New Paginated Version)
    function updateAttractions(attractions) {
        console.log("[DEBUG] updateAttractions - Top level (raw) attractions argument received:", attractions);

        if (attractions && attractions.length > 0) {
            console.log("[DEBUG] updateAttractions - First attraction object (raw):", attractions[0]);
            if (attractions[0]) {
                console.log("[DEBUG] updateAttractions - First attraction's location object (raw):", attractions[0].location);
            }
            if (attractions.length > 1 && attractions[1]) {
                console.log("[DEBUG] updateAttractions - Second attraction object (raw):", attractions[1]);
                if (attractions[1]) {
                    console.log("[DEBUG] updateAttractions - Second attraction's location object (raw):", attractions[1].location);
                }
            }
        }

        // Data integrity check
        if (attractions && attractions.length > 0) {
            console.log('[INFO] Performing data integrity check on received attractions...');
            for (let i = 0; i < attractions.length; i++) {
                const attr = attractions[i];
                if (!attr) {
                    console.error(`[VALIDATION_ERROR] Attraction at index ${i} is null or undefined.`);
                    continue;
                }
                if (typeof attr.image_url !== 'string' && attr.image_url !== null) {
                    console.error(`[VALIDATION_ERROR] Attraction '${attr.name || 'ID: '+attr.id}' (index ${i}) has invalid image_url:`, attr.image_url);
                }
                if (!attr.location) {
                    console.error(`[VALIDATION_ERROR] Attraction '${attr.name || 'ID: '+attr.id}' (index ${i}) is missing location object.`);
                } else {
                    if (typeof attr.location.lat !== 'number') {
                        console.error(`[VALIDATION_ERROR] Attraction '${attr.name || 'ID: '+attr.id}' (index ${i}) has invalid location.lat:`, attr.location.lat);
                    }
                    if (typeof attr.location.lng !== 'number') {
                        console.error(`[VALIDATION_ERROR] Attraction '${attr.name || 'ID: '+attr.id}' (index ${i}) has invalid location.lng:`, attr.location.lng);
                    }
                }
            }
            console.log('[INFO] Data integrity check complete.');
        }


        // Deep copy for logging to avoid issues with console displaying future states of objects
        try {
            console.log('[DEBUG] updateAttractions - Received attractions (deep copy for log):', JSON.parse(JSON.stringify(attractions)));
        } catch (e) {
            console.warn('[DEBUG] updateAttractions - Could not deep copy attractions for logging, showing raw:', attractions);
        }
        
        currentAttractions = attractions; // Store the full list
        currentRecommendationPage = 0; // Reset to first page
        selectedAttractions = state.selectedAttractions || []; // Initialize from state if exists

        if (!currentAttractions || currentAttractions.length === 0) { // Changed from attractions to currentAttractions
            attractionContentArea.innerHTML = '<p class="text-center text-muted">No recommendations available at the moment.</p>';
            recommendationsPaginationControls.classList.add('d-none');
            recommendationsPaginationControls.classList.remove('d-flex');
            confirmAllSelectionsFooter.classList.add('d-none');
            return;
        }

        renderCurrentAttractionPage();
        recommendationsPaginationControls.classList.remove('d-none');
        recommendationsPaginationControls.classList.add('d-flex');
        console.log("[DEBUG] Pagination controls classes:", recommendationsPaginationControls.className);
        console.log("[DEBUG] Pagination controls display style:", window.getComputedStyle(recommendationsPaginationControls).display);

        confirmAllSelectionsFooter.classList.remove('d-none');
    }

    function renderCurrentAttractionPage() {
        if (!currentAttractions || currentAttractions.length === 0) return;

        console.log(`[DEBUG] renderCurrentAttractionPage - current page index: ${currentRecommendationPage}`);
        const attraction = currentAttractions[currentRecommendationPage];

        // Log the structure of the attraction object AS IT IS RETRIEVED from currentAttractions
        if (attraction) {
            console.log("[DEBUG] renderCurrentAttractionPage - Attraction object from currentAttractions array:", JSON.parse(JSON.stringify(attraction)));
            console.log("[DEBUG] renderCurrentAttractionPage - Attraction's location object from currentAttractions array:", attraction.location ? JSON.parse(JSON.stringify(attraction.location)) : "LOCATION IS UNDEFINED OR NULL");
        } else {
            console.error(`[ERROR] renderCurrentAttractionPage - No attraction found in currentAttractions at index ${currentRecommendationPage}`);
        }
        
        if (!attraction) { // This check is now somewhat redundant due to the logging above, but keep for safety
            console.error(`[ERROR] No attraction data found for page index: ${currentRecommendationPage}`);
            attractionContentArea.innerHTML = '<p class="text-center text-muted">Error displaying attraction data.</p>';
            return;
        }
        console.log('[DEBUG] Rendering attraction:', JSON.parse(JSON.stringify(attraction))); // Deep copy for logging

        // Clear previous content
        attractionContentArea.innerHTML = '';

        const attractionPageDiv = document.createElement('div');
        attractionPageDiv.className = 'attraction-page p-2'; // Added padding

        let priceLevel = '';
        for (let i = 0; i < (attraction.price_level || 0); i++) {
            priceLevel += '💰';
        }
        let rating = attraction.rating ? `⭐ ${attraction.rating} (${attraction.user_ratings_total || 0} reviews)` : 'No rating';
        let duration = attraction.estimated_duration ? `${attraction.estimated_duration} hours (est.)` : 'Duration not specified';
        
        const isSelected = selectedAttractions.some(sa => sa.id === attraction.id);

        attractionPageDiv.innerHTML = `
            <div class="row">
                <div class="col-md-5">
                    <img src="${attraction.image_url || 'https://via.placeholder.com/300x200.png?text=No+Image'}" alt="${attraction.name || 'Attraction'}" class="img-fluid rounded mb-2 attraction-image" style="max-height: 200px; width: 100%; object-fit: cover;">
                    <h5 class="attraction-name mb-1">${attraction.name || 'Unknown Attraction'}</h5>
                    <p class="text-muted small mb-1">${attraction.address || ''}</p>
                </div>
                <div class="col-md-7">
                    <p class="mb-1"><strong>Category:</strong> ${attraction.category || 'N/A'}</p>
                    <p class="mb-1"><strong>Price:</strong> ${priceLevel || 'N/A'}</p>
                    <p class="mb-1"><strong>Rating:</strong> ${rating}</p>
                    <p class="mb-1"><strong>Duration:</strong> ${duration}</p>
                    <p class="mb-2"><em>${attraction.description || ''}</em></p>
                    <button class="btn btn-sm ${isSelected ? 'btn-success' : 'btn-outline-primary'} select-attraction-btn" data-attraction-id="${attraction.id}">
                        <i class="fas ${isSelected ? 'fa-check-circle' : 'fa-plus-circle'}"></i> ${isSelected ? 'Selected' : 'Select this Attraction'}
                    </button>
                </div>
            </div>
            <hr>
            <div class="row">
                 <div class="col-12 nearby-info-slot" id="nearby-info-${attraction.id}">
                    <p class="text-muted">Loading nearby information...</p>
                </div>
            </div>
        `;

        attractionContentArea.appendChild(attractionPageDiv);

        // Add event listener to the new select button
        const selectBtn = attractionPageDiv.querySelector('.select-attraction-btn');
        selectBtn.addEventListener('click', function() {
            toggleAttractionSelection(attraction, this);
        });

        // Fetch and display nearby places
        fetchNearbyPlaces(attraction, `nearby-info-${attraction.id}`);

        updatePaginationInfo();
    }

    function toggleAttractionSelection(attraction, button) {
        console.log("[DEBUG] toggleAttractionSelection called.");
        console.log("[DEBUG] typeof addMarkerToMap:", typeof addMarkerToMap);
        console.log("[DEBUG] typeof removeMarkerFromMap:", typeof removeMarkerFromMap);

        const index = selectedAttractions.findIndex(sa => sa.id === attraction.id);
        if (index > -1) {
            selectedAttractions.splice(index, 1); // Deselect
            removeMarkerFromMap(attraction.id); // Assuming you want to remove map marker
            button.classList.replace('btn-success', 'btn-outline-primary');
            button.innerHTML = `<i class="fas fa-plus-circle"></i> Select this Attraction`;
            console.log("[DEBUG] Select button DESELECTED. Classes:", button.className);
        } else {
            selectedAttractions.push(attraction); // Select
            addMarkerToMap(attraction); // Assuming you want to add map marker
            button.classList.replace('btn-outline-primary', 'btn-success');
            button.innerHTML = `<i class="fas fa-check-circle"></i> Selected`;
            console.log("[DEBUG] Select button SELECTED. Classes:", button.className);
        }
        state.selectedAttractions = selectedAttractions; // Update global state
        updateSelectedAttractionsList(selectedAttractions); // Update the list display on the left panel
    }

    function updatePaginationInfo() {
        attractionPageInfo.textContent = `Attraction ${currentRecommendationPage + 1} of ${currentAttractions.length}`;
        prevAttractionBtn.disabled = currentRecommendationPage === 0;
        nextAttractionBtn.disabled = currentRecommendationPage === currentAttractions.length - 1;
    }

    // Event listeners for pagination
    prevAttractionBtn.addEventListener('click', () => {
        if (currentRecommendationPage > 0) {
            currentRecommendationPage--;
            renderCurrentAttractionPage();
        }
    });

    nextAttractionBtn.addEventListener('click', () => {
        if (currentRecommendationPage < currentAttractions.length - 1) {
            currentRecommendationPage++;
            renderCurrentAttractionPage();
        }
    });
    
    // Event listener for the main confirm button
    confirmSelectedAttractionsBtn.addEventListener('click', () => {
        if (selectedAttractions.length > 0) {
            state.selectedAttractions = selectedAttractions; // Ensure state is up-to-date
            updateSelectedAttractionsList(selectedAttractions); // Update UI list
            processUserInput('Here are my selected attractions');
        } else {
            addChatMessage('Please select at least one attraction from the recommendations.', 'assistant');
        }
    });

    // Add marker to map
    function addMarkerToMap(attraction) {
        if (!map || !attraction || !attraction.location || typeof attraction.location.lat !== 'number' || typeof attraction.location.lng !== 'number') {
            console.error("[ERROR] addMarkerToMap: Invalid attraction data or map not initialized.", attraction);
            return;
        }

        const marker = L.marker([attraction.location.lat, attraction.location.lng], {
            icon: L.divIcon({
                className: `map-marker marker-${attraction.category || 'other'}`,
                html: `<i class="fas fa-map-marker-alt"></i>`,
                iconSize: [30, 30],
                iconAnchor: [15, 30]
            })
        }).addTo(map);
        
        marker.bindTooltip(attraction.name);
        marker.attractionId = attraction.id;
        
        const existingMarkerIndex = mapMarkers.findIndex(m => m.attractionId === attraction.id);
        if (existingMarkerIndex === -1) {
            mapMarkers.push(marker);
        } else {
            map.removeLayer(mapMarkers[existingMarkerIndex]);
            mapMarkers.splice(existingMarkerIndex, 1);
            mapMarkers.push(marker);
        }
        updateMapView();
    }

    // Remove marker from map
    function removeMarkerFromMap(attractionId) {
        const markerIndex = mapMarkers.findIndex(m => m.attractionId === attractionId);
        if (markerIndex !== -1) {
            map.removeLayer(mapMarkers[markerIndex]);
            mapMarkers.splice(markerIndex, 1);
        }
    }

    // Update map view to show all markers
    function updateMapView() {
        if (mapMarkers.length > 0) {
            const group = new L.featureGroup(mapMarkers);
            map.fitBounds(group.getBounds().pad(0.1));
        }
    }
    
    // Update itinerary display
    function updateItinerary(itinerary) {
        itineraryContainer.innerHTML = '';
        
        if (!itinerary || itinerary.length === 0) {
            itineraryContainer.innerHTML = '<p class="text-center text-muted">No itinerary available yet.</p>';
            return;
        }
        
        itinerary.forEach(day => {
            const dayCard = document.createElement('div');
            dayCard.className = 'card mb-3';
            
            let spotsHTML = '';
            day.spots.forEach(spot => {
                let priceLevel = '';
                for (let i = 0; i < (spot.price_level || 0); i++) {
                    priceLevel += '💰';
                }
                
                spotsHTML += `
                    <div class="card mb-2">
                        <div class="card-body py-2">
                            <h6 class="mb-1">${spot.name}</h6>
                            <p class="mb-0 small">
                                <span class="badge bg-primary">${spot.start_time} - ${spot.end_time}</span>
                                <span class="badge bg-secondary ms-1">${spot.category || 'attraction'}</span>
                                <span class="ms-2">${priceLevel}</span>
                            </p>
                        </div>
                    </div>
                `;
            });
            
            dayCard.innerHTML = `
                <div class="card-header bg-light">
                    <strong>Day ${day.day}</strong> - ${day.date}
                </div>
                <div class="card-body">
                    ${spotsHTML}
                </div>
            `;
            
            itineraryContainer.appendChild(dayCard);
        });
    }
    
    // Update budget display
    function updateBudget(budget) {
        const budgetDiv = document.getElementById('budget-container');
        if (!budgetDiv || !budget) return;
        budgetDiv.innerHTML = `
        <h5 class="mb-3">Budget Estimate</h5>
        <div class="row">
            <div class="col-md-6">
                <p class="mb-1"><strong>Total:</strong> $${Number(budget.total).toFixed(2)}</p>
                <p class="mb-1"><strong>Accommodation:</strong> $${Number(budget.accommodation).toFixed(2)}</p>
                <p class="mb-1"><strong>Food:</strong> $${Number(budget.food).toFixed(2)}</p>
            </div>
            <div class="col-md-6">
                <p class="mb-1"><strong>Transport:</strong> $${Number(budget.transport).toFixed(2)}</p>
                <p class="mb-1"><strong>Attractions:</strong> $${Number(budget.attractions).toFixed(2)}</p>
                ${budget.car_rental ? `<p class="mb-1"><strong>Car Rental:</strong> $${Number(budget.car_rental).toFixed(2)}</p>` : ''}
                ${budget.fuel_cost ? `<p class="mb-1"><strong>Fuel Cost:</strong> $${Number(budget.fuel_cost).toFixed(2)}</p>` : ''}
            </div>
        </div>
        `;
    }
    
    // Update confirmation display
    function updateConfirmation(response) {
        const confirmationDiv = document.getElementById('confirmation-container');
        if (!confirmationDiv) return;
        confirmationDiv.innerHTML = '';
        if (!response) {
            confirmationDiv.innerHTML = '<p class="text-center text-muted">Trip confirmation and details will appear here once generated.</p>';
            return;
        }
        // 支持 markdown 格式
        confirmationDiv.innerHTML = `<div class="message-content">${marked.parse(response)}</div>`;
    }
    
    // Reset conversation
    function resetConversation() {
        fetch('/api/reset')
            .then(() => {
                // Clear UI
                chatContainer.innerHTML = '';
                itineraryContainer.innerHTML = '<p class="text-center text-muted">Your travel plan will appear here once generated.</p>';
                recommendationsContainer.innerHTML = '<p class="text-center text-muted">Recommendations will appear here based on your preferences.</p>';
                
                // Clear map markers
                mapMarkers.forEach(marker => map.removeLayer(marker));
                mapMarkers = [];
                
                // Reset map view
                map.setView([48.8566, 2.3522], 13);
                
                // Reset state
                state = {
                    step: 'chat',
                    userInfo: {},
                    attractions: [],
                    selectedAttractions: [],
                    itinerary: null,
                    budget: null,
                    ai_recommendation_generated: false,
                    user_input_processed: false,
                    session_id: null
                };
                
                // Add initial welcome message
                addChatMessage(
`Welcome to your Travel AI Assistant! Tell me your name, and I'll help you plan your perfect trip. Let's start by gathering some information:
<ul>
  <li>Which city would you like to visit?</li>
  <li>How many days will you stay?</li>
  <li>What's your budget (low, medium, high)?</li>
  <li>How many people are traveling?</li>
  <li>Are you traveling with children, pets, or have any special requirements?</li>
  <li>What type of activities do you enjoy (e.g., adventure, relaxation, culture)?</li>
  <li>What's your health condition?</li>
</ul>
`, 'assistant');
            })
            .catch(error => {
                console.error('Error resetting conversation:', error);
            });
    }
    // Handle attraction selection
    function selectAttraction(attractionId) {
        if (!map) return;
        const attraction = currentAttractions.find(a => a.id === attractionId);
        if (!attraction) return;

        if (!selectedAttractions.some(a => a.id === attractionId)) {
            selectedAttractions.push(attraction);
            updateSelectedAttractionsList();

            const marker = L.marker([attraction.location.lat, attraction.location.lng], {
                icon: L.divIcon({
                    className: 'selected-marker',
                    html: '<div class="selected-marker-inner"></div>',
                    iconSize: [20, 20]
                })
            });
            selectedMarkersLayer.addLayer(marker);
        }
    }

    // Update selected attractions list
    function updateSelectedAttractionsList(attractions) {
        const selectedAttractionsList = document.getElementById('selected-attractions');
        if (!selectedAttractionsList) return;
        
        selectedAttractionsList.innerHTML = '';
        
        if (!attractions || attractions.length === 0) {
            selectedAttractionsList.innerHTML = '<p class="text-center text-muted">No attractions selected yet.</p>';
            return;
        }
        
        attractions.forEach(attraction => {
            const card = document.createElement('div');
            card.className = 'card mb-2';
            
            let priceLevel = '';
            for (let i = 0; i < (attraction.price_level || 0); i++) {
                priceLevel += '💰';
            }
            
            let rating = attraction.rating ? `⭐ ${attraction.rating}` : '';
            
            card.innerHTML = `
                <div class="card-body">
                    <h6 class="card-title mb-1">${attraction.name}</h6>
                    <p class="card-text mb-1">
                        <small class="text-muted">${attraction.category || 'attraction'}</small>
                        <small class="ms-2">${priceLevel}</small>
                        <small class="ms-2">${rating}</small>
                    </p>
                    <small class="text-muted">${attraction.estimated_duration || 2} hours</small>
                </div>
            `;
            
            selectedAttractionsList.appendChild(card);
        });
    }

    // Remove attraction from selection
    function removeAttraction(attractionId) {
        if (!map) return;
        const attraction = selectedAttractions.find(a => a.id === attractionId);
        if (!attraction) return;

        selectedAttractions = selectedAttractions.filter(a => a.id !== attractionId);
        updateSelectedAttractionsList();

        selectedMarkersLayer.eachLayer(layer => {
            if (layer.getLatLng().equals([attraction.location.lat, attraction.location.lng])) {
                selectedMarkersLayer.removeLayer(layer);
            }
        });
    }

    // Add new function to draw route on map
    function drawRoute(route) {
        if (!map || !route || route.length < 2) return;

        // Clear any existing route
        if (window.routeLayer) {
            map.removeLayer(window.routeLayer);
        }

        // Create a new layer for the route
        window.routeLayer = L.layerGroup().addTo(map);

        // const dayColors = ['#FF5733', '#33FF57', '#3357FF', '#FF33A1', '#A133FF', '#33FFA1', '#FFC300', '#C70039']; // Keep for marker colors if needed or define marker colors separately
        // const spotsByDay = {}; // No longer needed for polylines

        // // Group spots by day -- No longer needed for polylines
        // route.forEach(spot => {
        //     if (!spot.day) {
        //         console.warn("Spot missing day information:", spot);
        //         return; 
        //     }
        //     if (!spotsByDay[spot.day]) {
        //         spotsByDay[spot.day] = [];
        //     }
        //     spotsByDay[spot.day].push(spot);
        // });

        const allPolylinesGroup = L.featureGroup().addTo(window.routeLayer);

        // Draw a single polyline for the entire route with a default color
        const allPoints = route.map(spot => {
            if (spot.location && typeof spot.location.lat === 'number' && typeof spot.location.lng === 'number') {
                return [spot.location.lat, spot.location.lng];
            }
            return null; // Handle potential missing/invalid locations
        }).filter(p => p !== null); // Filter out null points

        if (allPoints.length > 1) {
            const polyline = L.polyline(allPoints, {
                color: '#7B8DAB', // New Primary Color (Soft Slate Blue)
                weight: 4,
                opacity: 0.75,
                smoothFactor: 1
            }).addTo(window.routeLayer);
            allPolylinesGroup.addLayer(polyline);
        }

        // // Draw polylines for each day -- REMOVED
        // for (const dayKey in spotsByDay) { ... }

        // Add markers for each point with numbers (iterating the original flat route for sequential numbering)
        route.forEach((spot, index) => {
            if (!spot.location || typeof spot.location.lat !== 'number' || typeof spot.location.lng !== 'number') {
                console.warn("Skipping marker for spot with invalid location:", spot);
                return;
            }
            // Determine day-specific class for the marker background
            const dayNumber = spot.day || 1; // Fallback to day 1 if not specified
            const markerBgClass = `day-${dayNumber}-marker-bg`;

            const marker = L.marker([spot.location.lat, spot.location.lng], {
                icon: L.divIcon({
                    className: `route-marker ${markerBgClass}`, // Add day-specific background class
                    html: `<div class="route-marker-number">${index + 1}</div>`,
                    iconSize: [24, 24],
                    iconAnchor: [12, 12] // Center the number icon
                })
            }).addTo(window.routeLayer);
            
            marker.bindPopup(`
                <h3>${spot.name || 'Unknown'}</h3>
                <p>Stop ${index + 1}</p>
            `);
        });
        
        // Fit bounds to show the entire route if any polylines were drawn
        if (Object.keys(allPolylinesGroup.getLayers()).length > 0) {
            map.fitBounds(allPolylinesGroup.getBounds().pad(0.1));
        } else if (route.length > 0) {
            // Fallback if no polylines (e.g., all days have 1 spot) but markers exist
            const singleMarkersGroup = L.featureGroup(route.map(spot => L.marker([spot.location.lat, spot.location.lng])));
            if (Object.keys(singleMarkersGroup.getLayers()).length > 0) {
                 map.fitBounds(singleMarkersGroup.getBounds().pad(0.2));
            }
        }
    }

    // Modify fetchNearbyPlaces function
    function fetchNearbyPlaces(attraction, containerId) {
        const nearbyContainer = document.getElementById(containerId);
        if (!nearbyContainer) {
            console.error('[ERROR] Nearby container not found for ID:', containerId);
            return;
        }
        nearbyContainer.innerHTML = '<p class="text-muted">Loading nearby information...</p>'; // Ensure this is set before fetch

        console.log('[DEBUG] fetchNearbyPlaces - Attraction:', JSON.parse(JSON.stringify(attraction)), 'Container ID:', containerId);
        if (!attraction || !attraction.location || typeof attraction.location.lat !== 'number' || typeof attraction.location.lng !== 'number') {
           console.error('[ERROR] Invalid attraction object or location for nearby search. Attraction object:', attraction);
           if (attraction) { // Log location details if attraction object itself exists
            console.error('[ERROR] Attraction location object:', attraction.location);
            if (attraction.location) {
                console.error(`[ERROR] Attraction location.lat: ${attraction.location.lat} (type: ${typeof attraction.location.lat})`);
                console.error(`[ERROR] Attraction location.lng: ${attraction.location.lng} (type: ${typeof attraction.location.lng})`);
            } else {
                console.error('[ERROR] attraction.location itself is undefined or null.');
            }
           } else {
            console.error('[ERROR] attraction object itself is undefined or null.');
           }

           if(nearbyContainer) nearbyContainer.innerHTML = '<p class="text-danger">Error: Invalid attraction data for nearby search.</p>';
           return;
        }

        // Use latitude and longitude instead of name
        const coordinates = `${attraction.location.lat},${attraction.location.lng}`;
        console.log(`[DEBUG] Fetching nearby for ${attraction.name} with coordinates: ${coordinates}`);

        fetch(`/api/nearby/${coordinates}`)
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                return response.json();
            })
            .then(data => {
                console.log(`[DEBUG] Nearby data received for ${attraction.name}:`, JSON.parse(JSON.stringify(data)));
                // Display nearby information in the specific container
                const nearbyMessage = formatNearbyPlacesMessage(data, attraction.name);
                nearbyContainer.innerHTML = marked.parse(nearbyMessage); // Use marked for consistency if needed
            })
            .catch(error => {
                console.error(`[ERROR] Error fetching nearby places for ${attraction.name}:`, error);
                nearbyContainer.innerHTML = '<p class="text-danger">Could not load nearby information. Check console for details.</p>';
            });
    }

    // Format nearby information message
    function formatNearbyPlacesMessage(data, attractionName) {
        let message = `<h6>Recommendations near ${attractionName}</h6>`;

        // Nearby Restaurants
        if (data.restaurants && data.restaurants.length > 0) {
            message += '<strong>🍽️ Nearby Restaurants:</strong><ul>';
            data.restaurants.forEach(restaurant => {
                message += `<li>`;
                if (restaurant.photos && restaurant.photos.length > 0) {
                    message += `<img src="${restaurant.photos[0].url}" style="max-width:100px; border-radius:4px; margin-right: 5px;" alt="${restaurant.name}">`;
                }
                message += `<strong>${restaurant.name}</strong> (${restaurant.type || 'Restaurant'}) - Rating: ${restaurant.rating || 'N/A'}⭐, Price: ${'💰'.repeat(restaurant.price_level || 0) || 'N/A'} <br><small>${restaurant.address || ''}</small>`;
                message += `</li>`;
            });
            message += '</ul>';
        } else {
            message += '<p>No nearby restaurants found.</p>';
        }
        
        // You can add other nearby types here (e.g., cafes, shops) if the API provides them

        return message;
    }

    // Make functions available globally
    window.updateMap = updateMap;
    window.selectAttraction = selectAttraction;
    window.removeAttraction = removeAttraction;
});
