import React, { useEffect, useState } from "react";
import axios from "axios";
import "./App.css";

function App() {
  const [records, setRecords] = useState([]);
  const [filter, setFilter] = useState("ALL");
  const [sourceFilter, setSourceFilter] = useState("ALL");

  const API_URL = "http://127.0.0.1:8000/api";

  const fetchRecords = async () => {
    try {
      const response = await axios.get(`${API_URL}/records/`);
      setRecords(response.data);
    } catch (error) {
      console.error("Error fetching records:", error);
    }
  };

  useEffect(() => {
    fetchRecords();
  }, []);

  const approveRecord = async (id) => {
    try {
      await axios.post(`${API_URL}/approve/${id}/`);
      fetchRecords();
    } catch (error) {
      console.error("Approve error:", error);
    }
  };

  const rejectRecord = async (id) => {
    try {
      await axios.post(`${API_URL}/reject/${id}/`);
      fetchRecords();
    } catch (error) {
      console.error("Reject error:", error);
    }
  };

  // Filter by status + source
  const filteredRecords = records.filter((record) => {
    const statusMatch =
      filter === "ALL" ? true :
      filter === "SUSPICIOUS" ? record.suspicious === true :
      record.status === filter;

    const sourceMatch =
      sourceFilter === "ALL" ? true : record.source_type === sourceFilter;

    return statusMatch && sourceMatch;
  });

  // Counts
  const totalCount = records.length;
  const pendingCount = records.filter((r) => r.status === "PENDING").length;
  const approvedCount = records.filter((r) => r.status === "APPROVED").length;
  const rejectedCount = records.filter((r) => r.status === "REJECTED").length;
  const suspiciousCount = records.filter((r) => r.suspicious === true).length;

  const totalCo2e = records
    .filter((r) => r.co2e_kg != null)
    .reduce((sum, r) => sum + r.co2e_kg, 0)
    .toFixed(1);

  const scopeColors = { "1": "#ef4444", "2": "#3b82f6", "3": "#8b5cf6" };

  return (
    <div style={{ padding: "30px", fontFamily: "Arial", backgroundColor: "#f9fafb", minHeight: "100vh" }}>

      <h1 style={{ marginBottom: "6px", fontSize: "24px" }}>ESG Emissions Dashboard</h1>
      <p style={{ color: "#6b7280", marginBottom: "28px", fontSize: "14px" }}>
        Total CO₂e ingested: <strong>{Number(totalCo2e).toLocaleString()} kg</strong>
      </p>

      {/* STATUS FILTER BUTTONS */}
      <div style={{ display: "flex", gap: "10px", marginBottom: "14px", flexWrap: "wrap" }}>
        {[
          { label: "All", value: "ALL", count: totalCount, color: "#3b82f6" },
          { label: "Pending", value: "PENDING", count: pendingCount, color: "#eab308" },
          { label: "Approved", value: "APPROVED", count: approvedCount, color: "#22c55e" },
          { label: "Rejected", value: "REJECTED", count: rejectedCount, color: "#ef4444" },
          { label: "Suspicious", value: "SUSPICIOUS", count: suspiciousCount, color: "#111827" },
        ].map(({ label, value, count, color }) => (
          <button
            key={value}
            onClick={() => setFilter(value)}
            style={{
              backgroundColor: filter === value ? color : "#e5e7eb",
              color: filter === value ? "white" : "#374151",
              border: "none",
              padding: "10px 16px",
              borderRadius: "6px",
              cursor: "pointer",
              fontWeight: "bold",
              fontSize: "13px",
              transition: "all 0.15s",
            }}
          >
            {label} ({count})
          </button>
        ))}
      </div>

      {/* SOURCE FILTER BUTTONS */}
      <div style={{ display: "flex", gap: "10px", marginBottom: "24px", flexWrap: "wrap" }}>
        {["ALL", "SAP", "UTILITY", "TRAVEL"].map((src) => (
          <button
            key={src}
            onClick={() => setSourceFilter(src)}
            style={{
              backgroundColor: sourceFilter === src ? "#1d4ed8" : "#dbeafe",
              color: sourceFilter === src ? "white" : "#1d4ed8",
              border: "none",
              padding: "7px 14px",
              borderRadius: "20px",
              cursor: "pointer",
              fontWeight: "600",
              fontSize: "12px",
            }}
          >
            {src}
          </button>
        ))}
      </div>

      {/* TABLE */}
      <div style={{ overflowX: "auto", borderRadius: "8px", boxShadow: "0 1px 3px rgba(0,0,0,0.1)" }}>
        <table
          cellPadding="12"
          cellSpacing="0"
          width="100%"
          style={{ borderCollapse: "collapse", backgroundColor: "white", fontSize: "13px" }}
        >
          <thead>
            <tr style={{ backgroundColor: "#f3f4f6", borderBottom: "2px solid #e5e7eb" }}>
              <th style={th}>Source</th>
              <th style={th}>Scope</th>
              <th style={th}>Category</th>
              <th style={th}>Date</th>
              <th style={th}>Raw Qty</th>
              <th style={th}>Normalised</th>
              <th style={th}>CO₂e (kg)</th>
              <th style={th}>Status</th>
              <th style={th}>Suspicious</th>
              <th style={th}>Actions</th>
            </tr>
          </thead>

          <tbody>
            {filteredRecords.map((record, idx) => (
              <tr
                key={record.id}
                style={{
                  backgroundColor: record.suspicious
                    ? "#fff7ed"
                    : idx % 2 === 0 ? "white" : "#f9fafb",
                  borderBottom: "1px solid #e5e7eb",
                }}
              >
                <td style={td}>{record.source_type}</td>

                <td style={td}>
                  <span style={{
                    backgroundColor: scopeColors[record.scope] || "#9ca3af",
                    color: "white",
                    borderRadius: "4px",
                    padding: "2px 8px",
                    fontSize: "11px",
                    fontWeight: "bold",
                  }}>
                    S{record.scope}
                  </span>
                </td>

                <td style={td}>{record.category}</td>

                <td style={{ ...td, color: "#6b7280" }}>{record.activity_date}</td>

                {/* FIX: was record.quantity / record.unit — now correct field names */}
                <td style={td}>
                  {record.raw_quantity != null
                    ? `${Number(record.raw_quantity).toLocaleString()} ${record.raw_unit}`
                    : "—"}
                </td>

                <td style={td}>
                  {record.normalized_quantity != null
                    ? `${Number(record.normalized_quantity).toLocaleString()} ${record.normalized_unit}`
                    : "—"}
                </td>

                <td style={{ ...td, fontWeight: "600" }}>
                  {record.co2e_kg != null
                    ? Number(record.co2e_kg).toLocaleString()
                    : "—"}
                </td>

                <td style={td}>
                  <span style={{
                    color:
                      record.status === "APPROVED" ? "#16a34a" :
                      record.status === "REJECTED" ? "#dc2626" : "#d97706",
                    fontWeight: "bold",
                  }}>
                    {record.status}
                  </span>
                </td>

                {/* FIX: was record.is_suspicious — now record.suspicious */}
                <td style={td}>
                  {record.suspicious ? (
                    <span title={record.suspicious_reason || ""} style={{
                      color: "#dc2626",
                      fontWeight: "bold",
                      cursor: record.suspicious_reason ? "help" : "default",
                      borderBottom: record.suspicious_reason ? "1px dashed #dc2626" : "none",
                    }}>
                      ⚠ YES
                    </span>
                  ) : (
                    <span style={{ color: "#6b7280" }}>—</span>
                  )}
                </td>

                <td style={td}>
                  {record.status === "PENDING" && (
                    <>
                      <button
                        onClick={() => approveRecord(record.id)}
                        style={btnGreen}
                      >
                        Approve
                      </button>
                      <button
                        onClick={() => rejectRecord(record.id)}
                        style={btnRed}
                      >
                        Reject
                      </button>
                    </>
                  )}
                  {record.status !== "PENDING" && (
                    <span style={{ color: "#9ca3af", fontSize: "12px" }}>
                      {record.status === "APPROVED" ? "✓ Done" : "✗ Done"}
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {filteredRecords.length === 0 && (
        <p style={{ marginTop: "20px", fontWeight: "bold", color: "gray", textAlign: "center" }}>
          No records found.
        </p>
      )}

      <p style={{ marginTop: "16px", fontSize: "12px", color: "#9ca3af" }}>
        Showing {filteredRecords.length} of {totalCount} records
      </p>
    </div>
  );
}

// Shared styles
const th = {
  textAlign: "left",
  padding: "12px 14px",
  fontWeight: "600",
  fontSize: "12px",
  color: "#374151",
  whiteSpace: "nowrap",
};

const td = {
  padding: "10px 14px",
  verticalAlign: "middle",
};

const btnGreen = {
  backgroundColor: "#22c55e",
  color: "white",
  border: "none",
  padding: "6px 12px",
  borderRadius: "5px",
  marginRight: "6px",
  cursor: "pointer",
  fontSize: "12px",
  fontWeight: "600",
};

const btnRed = {
  backgroundColor: "#ef4444",
  color: "white",
  border: "none",
  padding: "6px 12px",
  borderRadius: "5px",
  cursor: "pointer",
  fontSize: "12px",
  fontWeight: "600",
};

export default App;