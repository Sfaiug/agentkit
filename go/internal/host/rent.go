package host

// vmCPUs is the least a piece's VM gets, Python's helper.VM_CPUS.
const vmCPUs = 2

// MBPerCPU is the MiB each vCPU of a machine to rent must hold for a heavy piece, as Python's
// helper.cpu_mb rounds it up: its share of the piece's VM, twice the piece's memory as the VM
// holds its own kernel, page cache and clone too, beside the tenth the machine's system keeps.
func MBPerCPU() int {
	share := 9 * int(max(heavyCPUs, vmCPUs))
	return (2*heavyMemMB*10 + share - 1) / share
}
