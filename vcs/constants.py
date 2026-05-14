# constants.py

STATE_MAPPINGS = [
    # ── South India ──
    ['tamilnadu', 'tn', 'chennai', 'coimbatore', 'madurai', 'trichy', 'tiruchirappalli', 'salem', 'tirunelveli', 'tiruppur', 'vellore', 'erode', 'thoothukudi', 'hosur', 'kanyakumari', 'dindigul', 'thanjavur', 'karur', 'krishnagiri'],
    ['karnataka', 'ka', 'bangalore', 'bengaluru', 'mysore', 'mysuru', 'mangaluru', 'mangalore', 'hubli', 'hubballi', 'belgaum', 'belagavi', 'dharwad', 'gulbarga', 'davangere', 'bellary', 'shivamogga', 'tumkur', 'udupi'],
    ['kerala', 'kl', 'kochi', 'ernakulam', 'trivandrum', 'thiruvananthapuram', 'kozhikode', 'calicut', 'thrissur', 'kollam', 'palakkad', 'kannur', 'kottayam', 'alappuzha', 'malappuram', 'kasaragod'],
    ['telangana', 'ts', 'tg', 'hyderabad', 'warangal', 'secunderabad', 'nizamabad', 'karimnagar', 'khammam', 'ramagundam', 'mahabubnagar', 'nalgonda'],
    ['andhrapradesh', 'ap', 'visakhapatnam', 'vizag', 'vijayawada', 'guntur', 'tirupati', 'nellore', 'kurnool', 'rajahmundry', 'kakinada', 'kadapa', 'anantapur', 'chittoor', 'eluru', 'ongole'],
    
    # ── West India ──
    ['maharashtra', 'mh', 'mumbai', 'pune', 'nagpur', 'nashik', 'aurangabad', 'navi mumbai', 'thane', 'solapur', 'amravati', 'kolhapur', 'jalgaon', 'akola', 'latur', 'dhule', 'ahmednagar', 'kalyan', 'vasai'],
    ['gujarat', 'gj', 'ahmedabad', 'surat', 'vadodara', 'baroda', 'rajkot', 'gandhinagar', 'bhavnagar', 'jamnagar', 'junagadh', 'anand', 'bharuch', 'vapi', 'morbi', 'gandhidham', 'bhuj'],
    ['goa', 'ga', 'panaji', 'panjim', 'margao', 'vasco da gama', 'mapusa', 'ponda', 'marmagao'],
    
    # ── North India ──
    ['delhi', 'ncr', 'dl', 'new delhi', 'gurgaon', 'gurugram', 'noida', 'faridabad', 'ghaziabad', 'greater noida'],
    ['haryana', 'hr', 'gurgaon', 'gurugram', 'faridabad', 'panipat', 'ambala', 'karnal', 'rohtak', 'hisar', 'sonipat', 'panchkula', 'kurukshetra'],
    ['punjab', 'pb', 'chandigarh', 'ludhiana', 'amritsar', 'jalandhar', 'patiala', 'bathinda', 'mohali', 'pathankot', 'hoshiarpur', 'moga', 'khanna'],
    ['uttarpradesh', 'up', 'noida', 'lucknow', 'kanpur', 'agra', 'varanasi', 'meerut', 'allahabad', 'prayagraj', 'ghaziabad', 'bareilly', 'aligarh', 'moradabad', 'saharanpur', 'gorakhpur', 'jhansi', 'mathura'],
    ['uttarakhand', 'uk', 'dehradun', 'haridwar', 'roorkee', 'haldwani', 'rudrapur', 'rishikesh', 'kashipur'],
    ['himachalpradesh', 'hp', 'shimla', 'solan', 'dharamshala', 'mandi', 'baddi', 'kullu', 'kangra'],
    ['rajasthan', 'rj', 'jaipur', 'jodhpur', 'udaipur', 'kota', 'bikaner', 'ajmer', 'bhiwadi', 'alwar', 'bhilwara', 'sikar', 'pali', 'ganganagar'],
    
    # ── Central India ──
    ['madhyapradesh', 'mp', 'indore', 'bhopal', 'jabalpur', 'gwalior', 'ujjain', 'sagar', 'ratlam', 'rewa', 'satna', 'singrauli', 'dewas', 'katni'],
    ['chhattisgarh', 'cg', 'raipur', 'bhilai', 'bilaspur', 'korba', 'raigarh', 'durg', 'jagdalpur', 'ambikapur'],
    
    # ── East India ──
    ['westbengal', 'wb', 'kolkata', 'howrah', 'durgapur', 'asansol', 'siliguri', 'kharagpur', 'haldia', 'bardhaman', 'malda', 'darjeeling', 'jalpaiguri'],
    ['odisha', 'or', 'od', 'bhubaneswar', 'cuttack', 'rourkela', 'berhampur', 'sambalpur', 'puri', 'balasore', 'bhadrak', 'jharsuguda', 'angul'],
    ['bihar', 'br', 'patna', 'gaya', 'bhagalpur', 'muzaffarpur', 'purnia', 'darbhanga', 'arrah', 'begusarai', 'katihar'],
    ['jharkhand', 'jh', 'ranchi', 'jamshedpur', 'dhanbad', 'bokaro', 'deoghar', 'hazaribagh', 'giridih', 'ramgarh'],
    
    # ── North East India ──
    ['assam', 'as', 'guwahati', 'silchar', 'dibrugarh', 'jorhat', 'nagaon', 'tezpur', 'tinsukia', 'bongaigaon'],
    ['arunachalpradesh', 'ar', 'itanagar', 'naharlagun', 'pasighat'],
    ['manipur', 'mn', 'imphal', 'thoubal', 'churachandpur'],
    ['meghalaya', 'ml', 'shillong', 'tura', 'nongpoh'],
    ['mizoram', 'mz', 'aizawl', 'lunglei', 'champhai'],
    ['nagaland', 'nl', 'kohima', 'dimapur', 'mokokchung'],
    ['tripura', 'tr', 'agartala', 'udaipur', 'dharmanagar'],
    ['sikkim', 'sk', 'gangtok', 'namchi', 'gezing'],
    
    # ── Union Territories ──
    ['chandigarh', 'ch'],
    ['puducherry', 'py', 'pondicherry', 'oulgaret', 'karaikal', 'yanam', 'mahe'],
    ['jammu and kashmir', 'jk', 'srinagar', 'jammu', 'anantnag', 'baramulla'],
    ['ladakh', 'la', 'leh', 'kargil'],
    ['andaman and nicobar', 'an', 'port blair'],
    ['lakshadweep', 'ld', 'kavaratti'],
    ['dadra and nagar haveli', 'dn', 'daman', 'diu', 'silvassa']
]