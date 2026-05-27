"""Industry → category mapping and category → attribute fields."""

INDUSTRY_CATEGORIES = {
    "automotive": [
        "Engine Parts", "Body & Exterior", "Electrical", "Tires & Wheels",
        "Oils & Fluids", "Brakes", "Accessories", "Tools & Equipment",
    ],
    "architectural": [
        "Building Materials", "Fixtures", "Flooring", "Lighting",
        "Doors & Windows", "Hardware", "Paints & Finishes", "Plumbing",
    ],
    "construction": [
        "Power Tools", "Hand Tools", "Safety Gear", "Lumber",
        "Concrete & Masonry", "Electrical Supplies", "Plumbing Supplies", "Fasteners",
    ],
    "dental": [
        "Instruments", "Consumables", "Implants", "Imaging Equipment",
        "Lab Materials", "Sterilization", "Furniture", "PPE",
    ],
    "dry_cleaning": [
        "Solvents & Chemicals", "Pressing Equipment", "Hangers & Packaging",
        "Spotting Supplies", "Boilers & Steam", "Conveyors", "Detergents",
    ],
    "education": [
        "Books & Textbooks", "Stationery", "Lab Equipment", "Furniture",
        "Electronics", "Art Supplies", "Sports Equipment", "Uniforms",
    ],
    "electronics": [
        "Components", "Circuit Boards", "Cables & Connectors", "Displays",
        "Batteries & Power", "Sensors", "Enclosures", "Test Equipment",
    ],
    "food_beverage": [
        "Raw Ingredients", "Packaging", "Kitchen Equipment", "Refrigeration",
        "Beverages", "Baked Goods", "Dairy", "Frozen Foods",
    ],
    "healthcare": [
        "Medical Devices", "Pharmaceuticals", "Surgical Supplies", "Diagnostics",
        "Patient Care", "Lab Supplies", "PPE", "Furniture & Fixtures",
    ],
    "hospitality": [
        "Linens & Bedding", "Kitchen Equipment", "Cleaning Supplies", "Furniture",
        "Tableware", "Amenities", "Uniforms", "Technology",
    ],
    "law_office": [
        "Office Supplies", "Furniture", "Technology", "Filing & Storage",
        "Legal Forms", "Books & References", "Stationery", "Security",
    ],
    "logistics": [
        "Packaging Materials", "Pallets & Crates", "Labels & Tags",
        "Warehouse Equipment", "Vehicles & Parts", "Safety Gear", "Strapping & Tape",
    ],
    "manufacturing": [
        "Raw Materials", "Machine Parts", "Safety Equipment", "Cutting Tools",
        "Welding Supplies", "Lubricants", "Fasteners", "Measuring Instruments",
    ],
    "real_estate": [
        "Signage", "Lockboxes", "Staging Furniture", "Cleaning Supplies",
        "Photography Equipment", "Marketing Materials", "Office Supplies",
    ],
    "retail": [
        "Display & Fixtures", "POS Systems", "Packaging", "Signage",
        "Security Tags", "Shopping Bags", "Mannequins", "Lighting",
    ],
    "technology": [
        "Servers & Hardware", "Networking", "Software Licenses", "Peripherals",
        "Cables & Adapters", "Storage", "Security", "Cloud Services",
    ],
    "textiles": [
        "Fabrics", "Yarns & Threads", "Dyes & Chemicals", "Sewing Machines",
        "Buttons & Zippers", "Patterns", "Finished Garments", "Accessories",
    ],
    "wholesale": [
        "Bulk Food", "Household Goods", "Cleaning Products", "Office Supplies",
        "Industrial Supplies", "Personal Care", "Beverages", "Packaging",
    ],
    "other": [
        "General Supplies", "Equipment", "Consumables", "Parts & Components",
        "Services", "Other",
    ],
}

CATEGORY_FIELDS = {
    "_common": [
        {"name": "weight", "label": "Weight (kg)", "type": "number", "step": "0.01"},
        {"name": "dimensions", "label": "Dimensions (L x W x H cm)", "type": "text", "placeholder": "30 x 20 x 15"},
        {"name": "material", "label": "Material", "type": "text", "placeholder": "e.g. Stainless steel"},
        {"name": "brand", "label": "Brand", "type": "text", "placeholder": "e.g. DeWalt"},
        {"name": "model_number", "label": "Model Number", "type": "text", "placeholder": "e.g. DCD771C2"},
        {"name": "color", "label": "Color", "type": "text", "placeholder": "e.g. Black, Silver"},
        {"name": "warranty", "label": "Warranty", "type": "text", "placeholder": "e.g. 2 years"},
        {"name": "country_of_origin", "label": "Country of Origin", "type": "text", "placeholder": "e.g. USA"},
    ],
}
