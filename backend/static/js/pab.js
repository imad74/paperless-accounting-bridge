document.addEventListener("DOMContentLoaded", () => {
    const table = document.querySelector("[data-invoice-lines]");
    const addButton = document.querySelector("[data-add-invoice-line]");
    const emptyForm = document.querySelector("#invoice-line-empty-form");
    const totalForms = document.querySelector("#id_lines-TOTAL_FORMS");

    if (!table || !addButton || !emptyForm || !totalForms) {
        return;
    }

    const tbody = table.querySelector("tbody");

    const nextPosition = () => {
        const values = Array.from(
            tbody.querySelectorAll('input[name$="-position"]')
        )
            .filter((input) => {
                const row = input.closest("[data-invoice-line-row]");
                const deletion = row?.querySelector('input[name$="-DELETE"]');
                return !deletion?.checked;
            })
            .map((input) => Number.parseInt(input.value, 10))
            .filter(Number.isFinite);
        return values.length ? Math.max(...values) + 1 : 1;
    };

    addButton.addEventListener("click", () => {
        const index = Number.parseInt(totalForms.value, 10);
        const wrapper = document.createElement("tbody");
        wrapper.innerHTML = emptyForm.innerHTML.replaceAll("__prefix__", index);
        const row = wrapper.querySelector("[data-invoice-line-row]");
        const position = row.querySelector('input[name$="-position"]');
        position.value = nextPosition();
        tbody.append(row);
        totalForms.value = index + 1;
        row.querySelector('textarea[name$="-description"]').focus();
    });

    tbody.addEventListener("click", (event) => {
        const removeButton = event.target.closest("[data-remove-invoice-line]");
        if (!removeButton) {
            return;
        }
        const row = removeButton.closest("[data-invoice-line-row]");
        const deletion = row.querySelector('input[name$="-DELETE"]');
        deletion.checked = true;
        const errors = row.nextElementSibling;
        if (errors?.matches("[data-invoice-line-errors]")) {
            errors.hidden = true;
        }
        row.hidden = true;
    });
});
