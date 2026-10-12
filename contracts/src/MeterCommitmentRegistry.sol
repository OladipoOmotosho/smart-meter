// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";

/// @title MeterCommitmentRegistry
/// @notice Stores one fingerprint (a SHA-256 digest) per meter reading.
///         A fingerprint can be added once and never replaced.
/// @dev SPEC ONLY. The signatures, events and errors below are the agreed
///      interface. You write the storage and the function bodies.
///      See docs/BUILD_GUIDE.md, Step 2.
contract MeterCommitmentRegistry is AccessControl {
    /// Accounts with this role may commit fingerprints.
    bytes32 public constant AGGREGATOR_ROLE = keccak256("AGGREGATOR_ROLE");

    /// What is stored for each reading.
    struct Commitment {
        bytes32 digest;      // SHA-256 of the canonical reading bytes
        uint64 committedAt;  // block timestamp when it was committed
        address submitter;   // account that committed it
    }

    /// Emitted once for every successful commit.
    event Committed(
        bytes32 indexed recordKey,
        bytes32 digest,
        address indexed submitter,
        uint64 committedAt
    );

    /// A fingerprint already exists for this record key.
    error AlreadyCommitted(bytes32 recordKey);

    /// The digest is all zeros, which is never a real SHA-256 output here.
    error ZeroDigest();

    // TODO(Step 2): declare the storage that maps a record key to its Commitment.

    /// @param admin account that receives DEFAULT_ADMIN_ROLE and can grant AGGREGATOR_ROLE
    constructor(address admin) {
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
    }

    /// @notice Save the fingerprint for one reading.
    /// Requirements:
    ///  - only AGGREGATOR_ROLE may call it
    ///  - digest must not be zero (ZeroDigest)
    ///  - recordKey must not already have a commitment (AlreadyCommitted)
    ///  - store digest, block timestamp and msg.sender, then emit Committed
    function commit(bytes32 recordKey, bytes32 digest) external {
        recordKey; digest; // remove this line when you implement the function
        revert("TODO: Step 2");
    }

    /// @notice Return the stored commitment. All fields are zero if none exists.
    function getCommitment(bytes32 recordKey) external view returns (Commitment memory) {
        recordKey; // remove this line when you implement the function
        revert("TODO: Step 2");
    }

    /// @notice True if a fingerprint has been committed for this record key.
    function isCommitted(bytes32 recordKey) external view returns (bool) {
        recordKey; // remove this line when you implement the function
        revert("TODO: Step 2");
    }
}
